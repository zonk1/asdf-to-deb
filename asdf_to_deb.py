#!/usr/bin/env python3

import argparse
import os
import subprocess
import tempfile
import logging

logging.basicConfig(level=logging.INFO)

def create_dockerfile(tool, version):
    return f"""
FROM debian:bullseye

RUN apt-get update && apt-get install -y curl git build-essential fakeroot dpkg-dev

RUN git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.10.2
RUN echo '. $HOME/.asdf/asdf.sh' >> ~/.bashrc
RUN echo '. $HOME/.asdf/completions/asdf.bash' >> ~/.bashrc

SHELL ["/bin/bash", "-l", "-c"]

RUN asdf plugin add {tool}
RUN asdf install {tool} {version}
RUN asdf global {tool} {version}

RUN mkdir -p /root/debian/DEBIAN
RUN echo "Package: {tool}" > /root/debian/DEBIAN/control
RUN echo "Version: {version}" >> /root/debian/DEBIAN/control
RUN echo "Section: base" >> /root/debian/DEBIAN/control
RUN echo "Priority: optional" >> /root/debian/DEBIAN/control
RUN echo "Architecture: amd64" >> /root/debian/DEBIAN/control
RUN echo "Maintainer: ASDF Packager <packager@example.com>" >> /root/debian/DEBIAN/control
RUN echo "Description: {tool} packaged by ASDF" >> /root/debian/DEBIAN/control

RUN mkdir -p /root/debian/usr/local
RUN cp -R $HOME/.asdf/installs/{tool}/{version} /root/debian/usr/local/{tool}

RUN dpkg-deb --build /root/debian

CMD ["/bin/bash"]
"""

def main():
    parser = argparse.ArgumentParser(description="Package ASDF tool as Debian package")
    parser.add_argument("tool", help="ASDF-supported tool to package")
    parser.add_argument("output_dir", help="Directory to store the resulting Debian package")
    args = parser.parse_args()

    # Create a temporary directory for Docker context
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write initial Dockerfile to get the latest version
        initial_dockerfile = f"""
FROM debian:bullseye

RUN apt-get update && apt-get install -y curl git

RUN git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.10.2
RUN echo '. $HOME/.asdf/asdf.sh' >> ~/.bashrc
RUN echo '. $HOME/.asdf/completions/asdf.bash' >> ~/.bashrc

SHELL ["/bin/bash", "-l", "-c"]

RUN asdf plugin add {args.tool}
RUN asdf latest {args.tool}

CMD ["/bin/bash", "-c", "source ~/.bashrc && asdf latest {args.tool}"]
"""
        with open(os.path.join(tmpdir, "Dockerfile"), "w") as f:
            f.write(initial_dockerfile)

        # Build initial Docker image
        initial_image_name = f"{args.tool}-version-checker"
        subprocess.run(["docker", "build", "-t", initial_image_name, tmpdir], check=True)

        # Run Docker container to get the latest version
        try:
            result = subprocess.run(["docker", "run", "--rm", initial_image_name], 
                                    capture_output=True, text=True, check=True)
            version = result.stdout.strip()
            logging.info(f"Latest version of {args.tool}: {version}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error running Docker container: {e}")
            logging.error(f"Container stdout: {e.stdout}")
            logging.error(f"Container stderr: {e.stderr}")
            raise

        # Clean up initial image
        subprocess.run(["docker", "rmi", initial_image_name], check=True)

        # Write Dockerfile for building the package
        dockerfile_content = create_dockerfile(args.tool, version)
        with open(os.path.join(tmpdir, "Dockerfile"), "w") as f:
            f.write(dockerfile_content)

        # Build Docker image
        image_name = f"{args.tool}-deb-builder"
        subprocess.run(["docker", "build", "-t", image_name, tmpdir], check=True)

        # Run Docker container and copy the Debian package
        container_name = f"{args.tool}-deb-container"
        subprocess.run(["docker", "run", "--name", container_name, image_name], check=True)
        subprocess.run(["docker", "cp", f"{container_name}:/root/debian.deb", 
                        os.path.join(args.output_dir, f"{args.tool}_{version}_amd64.deb")], check=True)

        # Clean up
        subprocess.run(["docker", "rm", container_name], check=True)
        subprocess.run(["docker", "rmi", image_name], check=True)

    print(f"Debian package for {args.tool} version {version} has been created in {args.output_dir}")

if __name__ == "__main__":
    main()
