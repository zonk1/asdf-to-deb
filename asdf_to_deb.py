#!/usr/bin/env python3

import argparse
import os
import subprocess
import logging
import datetime
import getpass

logging.basicConfig(level=logging.ERROR)

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
        f"--user={uid}:{gid}",
        image_name,
        "bash", "-c", "source ~/.bashrc && tail -f /dev/null"
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

def main():
    parser = argparse.ArgumentParser(description="Package ASDF tool as Debian package")
    parser.add_argument("tool_name", help="ASDF-supported tool to package")
    parser.add_argument("-b", action="store_true", help="(re)build and keep base docker image")
    parser.add_argument("-v", metavar="version", help="Version of the tool to install")
    parser.add_argument("-u", metavar="user", default="asdf", help="User to remap root in container to")
    args = parser.parse_args()

    base_image = get_latest_base_image()

    if not base_image or args.b:
        logging.info("Base image not found or rebuild requested. Building base image...")
        base_image = build_base_image()
    elif is_image_older_than_week(base_image):
        if input("Base image is older than a week. Rebuild? (y/n): ").lower() == 'y':
            base_image = build_base_image()
    
    logging.info(f"Using base image: {base_image}")

    container_name = f"asdf-to-deb-{args.tool_name}"
    create_container(args.tool_name, base_image, args.u)

    try:
        # Install ASDF plugin
        docker_exec(container_name, f"asdf plugin add {args.tool_name}")

        # Get the version to install
        if args.v:
            version = args.v
        else:
            result = docker_exec(container_name, f"asdf latest {args.tool_name}")
            version = result.stdout.strip()

        # Install the tool
        docker_exec(container_name, f"asdf install {args.tool_name} {version}")
        docker_exec(container_name, f"asdf global {args.tool_name} {version}")

        # Create Debian package
        docker_exec(container_name, f"""
            mkdir -p /root/debian/DEBIAN /root/debian/usr
            echo "Package: {args.tool_name}" > /root/debian/DEBIAN/control
            echo "Version: {version}" >> /root/debian/DEBIAN/control
            echo "Section: base" >> /root/debian/DEBIAN/control
            echo "Priority: optional" >> /root/debian/DEBIAN/control
            echo "Architecture: amd64" >> /root/debian/DEBIAN/control
            echo "Maintainer: ASDF Packager <packager@example.com>" >> /root/debian/DEBIAN/control
            echo "Description: {args.tool_name} packaged by ASDF" >> /root/debian/DEBIAN/control
            cp -R $HOME/.asdf/installs/{args.tool_name}/{version}/* /root/debian/usr/
            dpkg-deb --build /root/debian
        """)

        # Copy the Debian package to the host
        command = ["docker", "cp", f"{container_name}:/root/debian.deb", f"{args.tool_name}_{version}_amd64.deb"]
        log_command(command)
        subprocess.run(command, check=True)

        print(f"Debian package for {args.tool_name} version {version} has been created: {args.tool_name}_{version}_amd64.deb")

    finally:
        # Clean up
        command = ["docker", "rm", "-f", container_name]
        log_command(command)
        subprocess.run(command, check=True)

if __name__ == "__main__":
    main()
def create_container(tool_name, image_name, user):
    container_name = f"asdf-to-deb-{tool_name}"
    uid = subprocess.run(["id", "-u", user], capture_output=True, text=True, check=True).stdout.strip()
    gid = subprocess.run(["id", "-g", user], capture_output=True, text=True, check=True).stdout.strip()
    
    result = subprocess.run([
        "docker", "run", "-d", "--name", container_name,
        "--cap-drop=all",
        "--cap-add=CHOWN", "--cap-add=FOWNER", "--cap-add=SETUID", "--cap-add=SETGID",
        "--security-opt=no-new-privileges",
        f"--user={uid}:{gid}",
        image_name,
        "tail", "-f", "/dev/null"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        logging.error(f"Failed to create container: {container_name}")
        logging.error(f"Error output: {result.stderr}")
        result.check_returncode()  # This will raise a CalledProcessError
    else:
        logging.info(f"Container created successfully: {container_name}")
