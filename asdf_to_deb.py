#!/usr/bin/env python3

import argparse
import os
import subprocess
import logging
import datetime
import getpass

logging.basicConfig(level=logging.INFO)

def build_base_image():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    image_name = f"asdf-to-deb:{timestamp}"
    
    dockerfile = f"""
FROM debian:sid

RUN apt-get update && apt-get install -y curl git build-essential fakeroot dpkg-dev

RUN git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.10.2
RUN echo '. $HOME/.asdf/asdf.sh' >> ~/.bashrc
RUN echo '. $HOME/.asdf/completions/asdf.bash' >> ~/.bashrc

SHELL ["/bin/bash", "-l", "-c"]
"""
    
    with open("Dockerfile", "w") as f:
        f.write(dockerfile)
    
    subprocess.run(["docker", "build", "-t", image_name, "."], check=True)
    os.remove("Dockerfile")
    return image_name

def get_latest_base_image():
    result = subprocess.run(["docker", "images", "asdf-to-deb", "--format", "{{.Tag}}"], 
                            capture_output=True, text=True, check=True)
    tags = result.stdout.strip().split('\n')
    return f"asdf-to-deb:{max(tags)}" if tags else None

def is_image_older_than_week(image_name):
    result = subprocess.run(["docker", "inspect", "-f", "{{.Created}}", image_name], 
                            capture_output=True, text=True, check=True)
    created_date = datetime.datetime.strptime(result.stdout.strip(), "%Y-%m-%dT%H:%M:%S.%fZ")
    return (datetime.datetime.now() - created_date).days > 7

def create_container(tool_name, image_name, user):
    container_name = f"asdf-to-deb-{tool_name}"
    uid = subprocess.run(["id", "-u", user], capture_output=True, text=True, check=True).stdout.strip()
    gid = subprocess.run(["id", "-g", user], capture_output=True, text=True, check=True).stdout.strip()
    
    subprocess.run([
        "docker", "run", "-d", "--name", container_name,
        "--cap-drop=all",
        "--cap-add=CHOWN", "--cap-add=FOWNER", "--cap-add=SETUID", "--cap-add=SETGID",
        "--security-opt=no-new-privileges",
        f"--user={uid}:{gid}",
        image_name,
        "tail", "-f", "/dev/null"
    ], check=True)

def main():
    parser = argparse.ArgumentParser(description="Package ASDF tool as Debian package")
    parser.add_argument("tool_name", help="ASDF-supported tool to package")
    parser.add_argument("-b", action="store_true", help="(re)build and keep base docker image")
    parser.add_argument("-v", metavar="version", help="Version of the tool to install")
    parser.add_argument("-u", metavar="user", default="asdf", help="User to remap root in container to")
    args = parser.parse_args()

    base_image = get_latest_base_image()

    if not base_image:
        logging.info("Base image not found. Building base image...")
        base_image = build_base_image()
    elif args.b:
        logging.info("Rebuild requested. Building base image...")
        base_image = build_base_image()
    elif is_image_older_than_week(base_image):
        if input("Base image is older than a week. Rebuild? (y/n): ").lower() == 'y':
            base_image = build_base_image()
    
    logging.info(f"Using base image: {base_image}")

    container_name = f"asdf-to-deb-{args.tool_name}"
    create_container(args.tool_name, base_image, args.u)

    try:
        # Install ASDF plugin
        subprocess.run(["docker", "exec", container_name, "asdf", "plugin", "add", args.tool_name], check=True)

        # Get the version to install
        if args.v:
            version = args.v
        else:
            result = subprocess.run(["docker", "exec", container_name, "asdf", "latest", args.tool_name], 
                                    capture_output=True, text=True, check=True)
            version = result.stdout.strip()

        # Install the tool
        subprocess.run(["docker", "exec", container_name, "asdf", "install", args.tool_name, version], check=True)
        subprocess.run(["docker", "exec", container_name, "asdf", "global", args.tool_name, version], check=True)

        # Create Debian package
        subprocess.run(["docker", "exec", container_name, "bash", "-c", f"""
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
        """], check=True)

        # Copy the Debian package to the host
        subprocess.run(["docker", "cp", f"{container_name}:/root/debian.deb", f"{args.tool_name}_{version}_amd64.deb"], check=True)

        print(f"Debian package for {args.tool_name} version {version} has been created: {args.tool_name}_{version}_amd64.deb")

    finally:
        # Clean up
        subprocess.run(["docker", "rm", "-f", container_name], check=True)

if __name__ == "__main__":
    main()
def create_container(tool_name, image_name, user):
    container_name = f"asdf-to-deb-{tool_name}"
    uid = subprocess.run(["id", "-u", user], capture_output=True, text=True, check=True).stdout.strip()
    gid = subprocess.run(["id", "-g", user], capture_output=True, text=True, check=True).stdout.strip()
    
    subprocess.run([
        "docker", "run", "-d", "--name", container_name,
        "--cap-drop=all",
        "--cap-add=CHOWN", "--cap-add=FOWNER", "--cap-add=SETUID", "--cap-add=SETGID",
        "--security-opt=no-new-privileges",
        f"--user={uid}:{gid}",
        image_name,
        "tail", "-f", "/dev/null"
    ], check=True)
