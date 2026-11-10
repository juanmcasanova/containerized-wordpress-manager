FROM php:8.5-fpm

ADD --chmod=0755 https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions /usr/local/bin/

# https://make.wordpress.org/hosting/handbook/server-environment/#php-extensions
RUN install-php-extensions apcu curl dom exif fileinfo gd igbinary imagick intl json hash mbstring mysqli opcache openssl timezonedb xml zip \
    # Cleanup
    && rm /usr/local/bin/install-php-extensions
