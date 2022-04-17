import pathlib

from setuptools import find_packages, setup

HERE = pathlib.Path(__file__).parent

README = (HERE / "README.md").read_text()

setup(
    name="xklb",
    version="1.0.0",
    description="xk library media database",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/chapmanjacobd/lb",
    author="chapmanjacobd",
    license="BSD 2-Clause",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
    ],
    packages=find_packages(exclude=("tests",)),
    include_package_data=True,
    install_requires=[
        "joblib",
        "rich",
        "pandas",
        "ipython",
        "python-dotenv",
        "subliminal",
        "catt",
        "sqlite-utils",
        "mutagen",
        "tinytag",
        "fuckit",
        "tabulate",
        "natsort",
    ],
    entry_points={
        "console_scripts": [
            "lb=lb.main:main",
        ]
    },
)
