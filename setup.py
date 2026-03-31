from setuptools import setup, find_packages

setup(
    name="mavica-tools",
    version="0.1.0",
    description="Floppy disk recovery and troubleshooting toolkit for Sony Mavica cameras",
    packages=find_packages(),
    python_requires=">=3.7",
    install_requires=[
        "Pillow>=9.0",
    ],
    entry_points={
        "console_scripts": [
            "mavica=mavica_tools.cli:main",
        ],
    },
)
