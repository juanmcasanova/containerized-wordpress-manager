import os
import shutil

import docker


def install_environment():
    # This should get "check" results to ensure we recreate anything that don't 100% comply
    # with our requirements (and so it doesn't file when some things exist but other don't)
    docker_client = docker.from_env()

    shutil.copyfile(f'{os.path.dirname(os.path.abspath(__file__))}/resources/haproxy.cfg', '/opt/containerized-wp-manager/haproxy.cfg')

    docker_client.networks.list()
    docker_client.networks.create('cwpm-services')
    docker_client.networks.create('cwpm-proxy')

    docker_client.containers.run(
        image='haproxy:3.4-alpine',
        detach=True,
        name='cwpm-haproxy',
        volumes=['/opt/containerized-wp-manager/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro'],
        ports={'80/tcp': 80},
        restart_policy={"Name": 'always'},
        network='cwpm-proxy'
    )
    docker_client.containers.run(
        image='mariadb:13.0',
        detach=True,
        name='cwpm-mariadb',
        volumes=['/opt/containerized-wp-manager/mariadb:/var/lib/mysql:Z'],
        ports={'3306/tcp': 3306},
        restart_policy={"Name": 'always'},
        network='cwpm-services',
        # TODO: Obviously, change this!
        # TODO: We should have a specific user for cwpm, never use root (and disable `root`@`%`)
        environment={'MARIADB_ROOT_PASSWORD': 'root'}
    )

    # Ensure the sites folder exists
    os.makedirs('/opt/containerized-wp-manager/sites')
