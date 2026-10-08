from setuptools import find_packages, setup

package_name = 'odi_first_encounter'

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
    maintainer='kim',
    maintainer_email='ehrud2235@naver.com',
    description=(
        'OpenAI-powered first encounter action server for ODI.'
    ),
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            (
                'first_encounter_node = '
                'odi_first_encounter.first_encounter_node:main'
            ),

        ],
    },
)
