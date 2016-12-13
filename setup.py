import os
import ast
from setuptools import setup


PACKAGE_NAME = 'music163'


def load_description(fname):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, fname)) as f:
        return f.read().strip()


def get_version(fname):
    with open(fname) as f:
        source = f.read()
    module = ast.parse(source)
    for e in module.body:
        if isinstance(e, ast.Assign) and \
                len(e.targets) == 1 and \
                e.targets[0].id == '__version__' and \
                isinstance(e.value, ast.Str):
            return e.value.s
    raise RuntimeError('__version__ not found')


setup(
    name='music163',
    packages=['music163'],
    version=get_version('{}/version.py'.format(PACKAGE_NAME)),
    description='Yet another cli client for music.163.com',
    long_description=load_description('README.rst'),
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.5',
    ],
    author='Kay Zheng',
    author_email='l04m33@gmail.com',
    url='https://github.com/l04m33/music163',
    license='MIT',
    zip_safe=False,
    install_requires=[
        'lxml >= 3.4.4',
        'pycrypto >= 2.6.1',
        'requests >= 2.8.1',
    ],
    entry_points='''
    [console_scripts]
    {0} = {0}.__main__:main
    '''.format(PACKAGE_NAME),
)
