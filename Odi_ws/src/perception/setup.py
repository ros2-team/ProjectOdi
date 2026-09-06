from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'perception'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='kim',
    maintainer_email='ehrud2235@naver.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'vlm_node = perception.vlm_node:main',
            'yolo_node = perception.yolo_node:main',
            'coordinator_node = perception.coordinator:main',

            'map_trinary_node = perception.map_trinary:main',
            'object_locater_node = perception.object_locater:main',

            'yolo_test_node = perception.yolo_test_0821:main',
            'vlm_test_node = perception.vlm_test_0821:main',
            'cord_test_node = perception.cord_test_0821:main',
            'yolo_test = perception.yolo_test:main',

            'bearing_probe_node = perception.bearing_probe:main',
        ],
    },
)
