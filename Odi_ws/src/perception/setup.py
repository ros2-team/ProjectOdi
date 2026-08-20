from setuptools import find_packages, setup

package_name = 'perception'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
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
            'yolo_test_node = perception.yolo_test:main',
            'map_trinary_node = perception.map_trinary:main',
            'object_locater_node = perception.object_locater:main',
            'bearing_probe_node = perception.bearing_probe:main',
        ],
    },
)
