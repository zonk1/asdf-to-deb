# ASDF to DEB Packager

This project provides a tool to package ASDF-managed tools into Debian packages (.deb files). It uses Docker to create a controlled environment for building the packages.

## Features

- Automatically builds Debian packages for ASDF-managed tools
- Supports building multiple tools in parallel
- Uses Docker for a consistent build environment
- Allows specifying custom tool versions and plugin repositories

## Prerequisites

- Docker
- Python 3.x

## Usage

Basic usage:

```
python3 asdf_to_deb.py [tool_name] [tool_plugin_repo]
```

Options:

- `-b`: (Re)build and keep the base Docker image
- `-v VERSION`: Specify the version of the tool to install
- `-u USER`: User to remap root in the container to (default: asdf)
- `-d`: Enable debug level logs
- `-t TARGET_DIR`: Target directory for the created .deb packages
- `-p PARALLEL`: Number of parallel builds (default: 8)

## Configuration

You can define a list of tools to build in the `tools.py` file. Each entry should be a tuple containing the tool name and its plugin repository (or None if using the default repository).

Example `tools.py`:

```python
tools = (
    ('fx', None),
    ('gitui', None),
    ('golangci-lint', 'https://github.com/hypnoglow/asdf-golangci-lint'),
    # Add more tools here
)
```

## License

[Specify your license here]

## Contributing

[Add contribution guidelines if applicable]
