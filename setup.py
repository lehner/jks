from setuptools import setup, find_packages
import glob

scripts = glob.glob("scripts/*")

setup(
    name="jks-system",
    version="1.0.0",
    packages=find_packages(),  # Automatically find the packages in the project
    scripts=scripts,  # Include scripts as is
    entry_points={},
    install_requires=["scipy","lz4","numpy"],  # List your package dependencies here
    author="Christoph Lehner",
    author_email="christoph@lhnr.de",
    description="JKS Measurement database system",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/lehner/jks",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)
