import os
from glob import glob
from setuptools import find_packages, setup


package_name = 'odi_behavior_executor'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name]
        ),
        (
            'share/' + package_name,
            ['package.xml']
        ),
        (
            os.path.join(
                "share",
                package_name,
                "launch",
            ),
            glob("launch/*.launch.py"),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ssu4645',
    maintainer_email='kws991108@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            "behavior_executor = odi_behavior_executor.behavior_executor_node:main",
            "dummy_perception = odi_behavior_executor.dummy_perception:main",
            "dummy_curiosity = odi_behavior_executor.dummy_curiosity:main",
            "dummy_observation = odi_behavior_executor.dummy_observation:main",
            "dummy_exploration = odi_behavior_executor.dummy_exploration:main",
        ],
    },
)
