from setuptools import find_packages, setup

package_name = 'odi_return_home'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ssu4645',
    maintainer_email='kws991108@gmail.com',
    description='Nav2 ReturnHome action server for ODI.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            (
                'return_home_node = '
                'odi_return_home.return_home_node:main'
            ),
        ],
    },
)
