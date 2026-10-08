from setuptools import setup
setup(name='odi_normal', version='0.1.0', packages=['odi_normal'],
      data_files=[('share/ament_index/resource_index/packages', ['resource/odi_normal']),
                  ('share/odi_normal', ['package.xml'])],
      install_requires=['setuptools'], zip_safe=True,
      maintainer='ODI team', maintainer_email='kws991108@gmail.com',
      description='Companion mode and Uno head bridge', license='Apache-2.0',
      entry_points={'console_scripts': [
          'normal_node = odi_normal.normal_node:main',
          'head_bridge = odi_normal.head_bridge:main']})

