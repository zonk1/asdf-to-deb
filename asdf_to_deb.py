#!/usr/bin/env python3

import argparse
import os
import subprocess
import logging
import datetime
import getpass
import shlex

from shlex import quote as shesc

logging.basicConfig(level=logging.ERROR)

def set_log_level(debug):
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

def log_command(command):
    logging.debug(f"Executing command: " + " ".join([shesc(arg) for arg in command]))

def build_base_image():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    image_name = f"asdf-to-deb:{timestamp}"
    
    dockerfile = f"""
FROM debian:unstable

RUN apt-get update && apt-get install -y curl git build-essential fakeroot dpkg-dev

RUN git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.10.2
RUN echo '. $HOME/.asdf/asdf.sh' >> ~/.bashrc
RUN echo '. $HOME/.asdf/completions/asdf.bash' >> ~/.bashrc

SHELL ["/bin/bash", "-l", "-c"]
"""
    
    with open("Dockerfile", "w") as f:
        f.write(dockerfile)
    
    command = ["docker", "build", "-t", image_name, "."]
    log_command(command)
    subprocess.run(command, check=True)
    os.remove("Dockerfile")
    return image_name

def get_latest_base_image():
    command = ["docker", "images", "asdf-to-deb", "--format", "{{.Tag}}"]
    log_command(command)
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    tags = result.stdout.strip().split('\n')
    return f"asdf-to-deb:{max(tags)}" if tags and tags[0] else None

def is_image_older_than_week(image_name):
    command = ["docker", "inspect", "-f", "{{.Created}}", image_name]
    log_command(command)
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    created_date = datetime.datetime.strptime(result.stdout.strip().split('.')[0], "%Y-%m-%dT%H:%M:%S")
    return (datetime.datetime.now() - created_date).days > 7

def create_container(tool_name, image_name, user):
    container_name = f"asdf-to-deb-{tool_name}"
    uid_command = ["id", "-u", user]
    log_command(uid_command)
    uid = subprocess.run(uid_command, capture_output=True, text=True, check=True).stdout.strip()
    
    gid_command = ["id", "-g", user]
    log_command(gid_command)
    gid = subprocess.run(gid_command, capture_output=True, text=True, check=True).stdout.strip()
    
    command = [
        "docker", "run", "-d", "--name", container_name,
        "--cap-drop=all",
        "--cap-add=CHOWN", "--cap-add=FOWNER", "--cap-add=SETUID", "--cap-add=SETGID",
        "--security-opt=no-new-privileges",
        #f"--user={uid}:{gid}",
        image_name,
        "tail", "-f", "/dev/null",
    ]
    log_command(command)
    subprocess.run(command, check=True)

def docker_exec(container_name, command):
    docker_command = ["docker", "exec", container_name, "bash", "-c", f"source ~/.bashrc && {command}"]
    log_command(docker_command)
    result = subprocess.run(docker_command, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"Command failed: {command}")
        logging.error(f"Error output: {result.stderr}")
        result.check_returncode()  # This will raise a CalledProcessError
    return result

def build_tool(tool_name, tool_plugin_repo, version, target_dir, base_image, user):

    container_name = f"asdf-to-deb-{tool_name}"
    create_container(tool_name, base_image, user)

    try:
        # Install ASDF plugin
        plugin_repo = shesc(tool_plugin_repo) if tool_plugin_repo else ""
        docker_exec(container_name, f"asdf plugin add {shesc(tool_name)} {plugin_repo}")

        # Get the version to install if not provided
        if not version:
            result = docker_exec(container_name, f"asdf latest {shesc(tool_name)}")
            version = result.stdout.strip()

        # Check if the Debian package already exists
        deb_path = os.path.join(target_dir, f"{tool_name}_{version}_amd64.deb")
        if os.path.exists(deb_path):
            logging.info(f"Debian package for {tool_name} version {version} already exists in the target directory.")
            return None

        # Install the tool
        docker_exec(container_name, f"asdf install {shesc(tool_name)} {shesc(version)}")
        docker_exec(container_name, f"asdf global {shesc(tool_name)} {shesc(version)}")

        # Create Debian package
        docker_exec(container_name, f"""
            mkdir -p /root/debian/DEBIAN /root/debian/usr
            echo "Package: {shesc(tool_name)}" > /root/debian/DEBIAN/control
            echo "Version: {shesc(version)}" >> /root/debian/DEBIAN/control
            echo "Section: base" >> /root/debian/DEBIAN/control
            echo "Priority: optional" >> /root/debian/DEBIAN/control
            echo "Architecture: amd64" >> /root/debian/DEBIAN/control
            echo "Maintainer: ASDF-TO-DEB Packager <sleepy.tent0234@fastmail.com>" >> /root/debian/DEBIAN/control
            echo "Description: {shesc(tool_name)} packaged by ASDF" >> /root/debian/DEBIAN/control
            cp -R $HOME/.asdf/installs/{shesc(tool_name)}/{shesc(version)}/* /root/debian/usr/
            dpkg-deb --build /root/debian
        """)

        # Create target directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)

        # Copy the Debian package to the host
        target_path = os.path.join(target_dir, f"{tool_name}_{version}_amd64.deb")
        command = ["docker", "cp", f"{container_name}:/root/debian.deb", target_path]
        log_command(command)
        subprocess.run(command, check=True)

        print(f"Debian package for {tool_name} version {version} has been created: {target_path}")
        return target_path

    except subprocess.CalledProcessError as e:
        logging.error(f"Error building tool: {e}")
        return None

    finally:
        # Clean up
        command = ["docker", "rm", "-f", container_name]
        log_command(command)
        subprocess.run(command, check=True)

def main():
    parser = argparse.ArgumentParser(description="Package ASDF tool as Debian package")
    parser.add_argument("tool_name", help="ASDF-supported tool to package")
    parser.add_argument("tool_plugin_repo", help="ASDF plugin git repo (for plugins not in official ASDF", nargs="?")
    parser.add_argument("-b", action="store_true", help="(re)build and keep base docker image")
    parser.add_argument("-v", metavar="version", help="Version of the tool to install")
    parser.add_argument("-u", metavar="user", default="asdf", help="User to remap root in container to")
    parser.add_argument("-d", action="store_true", help="Enable debug level logs")
    parser.add_argument("-t", metavar="target_dir", default=".", help="Target directory for the created deb package")
    args = parser.parse_args()

    set_log_level(args.d)

    base_image = get_latest_base_image()

    if not base_image or args.b:
        logging.info("Base image not found or rebuild requested. Building base image...")
        base_image = build_base_image()
    elif is_image_older_than_week(base_image):
        if input("Base image is older than a week. Rebuild? (y/n): ").lower() == 'y':
            base_image = build_base_image()
    
    logging.info(f"Using base image: {base_image}")

    build_tool(args.tool_name, args.tool_plugin_repo, args.v, args.t, base_image, args.u)

if __name__ == "__main__":
    main()

