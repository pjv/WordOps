import getpass
import glob
import os
import random
import json
import re
import string
import subprocess
import csv
from subprocess import CalledProcessError

from wo.cli.plugins.sitedb import getSiteInfo
from wo.cli.plugins.stack import WOStackController
from wo.core.aptget import WOAptGet
from wo.core.fileutils import WOFileUtils
from wo.core.git import WOGit
from wo.core.logging import Log
from wo.core.mysql import WOMysql
from wo.core.services import WOService
from wo.cli.plugins.stack_pref import post_pref
from wo.core.shellexec import CommandExecutionError, WOShellExec
from wo.core.sslutils import SSL
from wo.core.variables import WOVariables


class SiteError(Exception):
    """Custom Exception Occured when setting up site"""

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return repr(self.message)


def pre_run_checks(self):

    # Check nginx configuration
    Log.info(self, "Running pre-update checks, please wait...")
    try:
        Log.debug(self, "checking NGINX configuration ...")
        FNULL = open('/dev/null', 'w')
        subprocess.check_call(["/usr/sbin/nginx", "-t"], stdout=FNULL,
                              stderr=subprocess.STDOUT)
    except CalledProcessError as e:
        Log.debug(self, "{0}".format(str(e)))
        raise SiteError("nginx configuration check failed.")


def check_domain_exists(self, domain):
    if getSiteInfo(self, domain):
        return True
    return False


def setupdomain(self, data):

    # for debug purpose
    # for key, value in data.items() :
    #     print (key, value)

    wo_domain_name = data['site_name']
    wo_site_webroot = data['webroot']

    # Check if nginx configuration already exists
    # if os.path.isfile('/etc/nginx/sites-available/{0}'
    #                   .format(wo_domain_name)):
    #     raise SiteError("nginx configuration already exists for site")

    Log.info(self, "Setting up NGINX configuration \t", end='')
    # write nginx config for file
    try:
        wo_site_nginx_conf = open('/etc/nginx/sites-available/{0}'
                                  .format(wo_domain_name), encoding='utf-8',
                                  mode='w')
        if not data['php73']:
            self.app.render((data), 'virtualconf.mustache',
                            out=wo_site_nginx_conf)
        else:
            self.app.render((data), 'virtualconf-php7.mustache',
                            out=wo_site_nginx_conf)
        wo_site_nginx_conf.close()
    except IOError as e:
        Log.debug(self, str(e))
        raise SiteError("create nginx configuration failed for site")
    except Exception as e:
        Log.debug(self, str(e))
        raise SiteError("create nginx configuration failed for site")
    finally:
        # Check nginx -t and return status over it
        try:
            Log.debug(self, "Checking generated nginx conf, please wait...")
            FNULL = open('/dev/null', 'w')
            subprocess.check_call(["/usr/sbin/nginx", "-t"], stdout=FNULL,
                                  stderr=subprocess.STDOUT)
            Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")
        except CalledProcessError as e:
            Log.debug(self, "{0}".format(str(e)))
            Log.info(self, "[" + Log.ENDC + Log.FAIL + "Fail" +
                     Log.OKBLUE + "]")
            raise SiteError("created nginx configuration failed for site."
                            " check with `nginx -t`")

    # create symbolic link for
    WOFileUtils.create_symlink(self, ['/etc/nginx/sites-available/{0}'
                                      .format(wo_domain_name),
                                      '/etc/nginx/sites-enabled/{0}'
                                      .format(wo_domain_name)])

    # Creating htdocs & logs directory
    Log.info(self, "Setting up webroot \t\t", end='')
    try:
        if not os.path.exists('{0}/htdocs'.format(wo_site_webroot)):
            os.makedirs('{0}/htdocs'.format(wo_site_webroot))
        if not os.path.exists('{0}/logs'.format(wo_site_webroot)):
            os.makedirs('{0}/logs'.format(wo_site_webroot))
        if not os.path.exists('{0}/conf/nginx'.format(wo_site_webroot)):
            os.makedirs('{0}/conf/nginx'.format(wo_site_webroot))

        WOFileUtils.create_symlink(self, ['/var/log/nginx/{0}.access.log'
                                          .format(wo_domain_name),
                                          '{0}/logs/access.log'
                                          .format(wo_site_webroot)])
        WOFileUtils.create_symlink(self, ['/var/log/nginx/{0}.error.log'
                                          .format(wo_domain_name),
                                          '{0}/logs/error.log'
                                          .format(wo_site_webroot)])
    except Exception as e:
        Log.debug(self, str(e))
        raise SiteError("setup webroot failed for site")
    finally:
        # TODO Check if directories are setup
        if (os.path.exists('{0}/htdocs'.format(wo_site_webroot)) and
                os.path.exists('{0}/logs'.format(wo_site_webroot))):
            Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")
        else:
            Log.info(self, "[" + Log.ENDC + "Fail" + Log.OKBLUE + "]")
            raise SiteError("setup webroot failed for site")


def setupdatabase(self, data):
    wo_domain_name = data['site_name']
    wo_random_pass = (''.join(random.sample(string.ascii_uppercase +
                                            string.ascii_lowercase +
                                            string.digits, 24)))
    wo_replace_dot = wo_domain_name.replace('.', '')
    prompt_dbname = self.app.config.get('mysql', 'db-name')
    prompt_dbuser = self.app.config.get('mysql', 'db-user')
    wo_mysql_grant_host = self.app.config.get('mysql', 'grant-host')
    wo_db_name = ''
    wo_db_username = ''
    wo_db_password = ''

    if prompt_dbname == 'True' or prompt_dbname == 'true':
        try:
            wo_db_name = input('Enter the MySQL database name [{0}]: '
                               .format(wo_replace_dot))
        except EOFError:
            raise SiteError("Unable to input database name")

    if not wo_db_name:
        wo_db_name = wo_replace_dot
        wo_db_name = (wo_db_name[0:8] + generate_random())

    if prompt_dbuser == 'True' or prompt_dbuser == 'true':
        try:
            wo_db_username = input('Enter the MySQL database user name [{0}]: '
                                   .format(wo_replace_dot))
            wo_db_password = getpass.getpass(prompt='Enter the MySQL database'
                                             ' password [{0}]: '
                                             .format(wo_random_pass))
        except EOFError:
            raise SiteError("Unable to input database credentials")

    if not wo_db_username:
        wo_db_username = wo_replace_dot
        wo_db_username = (wo_db_name[0:8] + generate_random())
    if not wo_db_password:
        wo_db_password = wo_random_pass

    # create MySQL database
    Log.info(self, "Setting up database\t\t", end='')
    Log.debug(self, "Creating database {0}".format(wo_db_name))
    try:
        if WOMysql.check_db_exists(self, wo_db_name):
            Log.debug(self, "Database already exists, Updating DB_NAME .. ")
            wo_db_name = (wo_db_name[0:8] + generate_random())
            wo_db_username = (wo_db_name[0:8] + generate_random())
    except MySQLConnectionError:
        raise SiteError("MySQL Connectivity problem occured")

    try:
        WOMysql.execute(self, "create database `{0}`"
                        .format(wo_db_name))
    except StatementExcecutionError:
        Log.info(self, "[" + Log.ENDC + Log.FAIL + "Failed" + Log.OKBLUE + "]")
        raise SiteError("create database execution failed")
    # Create MySQL User
    Log.debug(self, "Creating user {0}".format(wo_db_username))
    Log.debug(self, "create user `{0}`@`{1}` identified by ''"
              .format(wo_db_username, wo_mysql_grant_host))
    try:
        WOMysql.execute(self,
                        "create user `{0}`@`{1}` identified by '{2}'"
                        .format(wo_db_username, wo_mysql_grant_host,
                                wo_db_password), log=False)
    except StatementExcecutionError:
        Log.info(self, "[" + Log.ENDC + Log.FAIL + "Failed" + Log.OKBLUE + "]")
        raise SiteError("creating user failed for database")

    # Grant permission
    Log.debug(self, "Setting up user privileges")
    try:
        WOMysql.execute(self,
                        "grant all privileges on `{0}`.* to `{1}`@`{2}`"
                        .format(wo_db_name,
                                wo_db_username, wo_mysql_grant_host))
    except StatementExcecutionError:
        Log.info(self, "[" + Log.ENDC + Log.FAIL + "Failed" + Log.OKBLUE + "]")
        SiteError("grant privileges to user failed for database ")

    Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")

    data['wo_db_name'] = wo_db_name
    data['wo_db_user'] = wo_db_username
    data['wo_db_pass'] = wo_db_password
    data['wo_db_host'] = WOVariables.wo_mysql_host
    data['wo_mysql_grant_host'] = wo_mysql_grant_host
    return(data)


def setupwordpress(self, data, vhostonly=False):
    wo_domain_name = data['site_name']
    wo_site_webroot = data['webroot']
    prompt_wpprefix = self.app.config.get('wordpress', 'prefix')
    wo_wp_user = self.app.config.get('wordpress', 'user')
    wo_wp_pass = self.app.config.get('wordpress', 'password')
    wo_wp_email = self.app.config.get('wordpress', 'email')
    # Random characters
    wo_random_pass = (''.join(random.sample(string.ascii_uppercase +
                                            string.ascii_lowercase +
                                            string.digits, 24)))
    wo_wp_prefix = ''
    # wo_wp_user = ''
    # wo_wp_pass = ''

    if 'wp-user' in data.keys() and data['wp-user']:
        wo_wp_user = data['wp-user']
    if 'wp-email' in data.keys() and data['wp-email']:
        wo_wp_email = data['wp-email']
    if 'wp-pass' in data.keys() and data['wp-pass']:
        wo_wp_pass = data['wp-pass']

    Log.info(self, "Downloading WordPress \t\t", end='')
    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))
    try:
        if WOShellExec.cmd_exec(self, "wp --allow-root core"
                                " download"):
            pass
        else:
            Log.info(self, "[" + Log.ENDC + Log.FAIL +
                     "Fail" + Log.OKBLUE + "]")
            raise SiteError("download WordPress core failed")
    except CommandExecutionError:
        Log.info(self, "[" + Log.ENDC + Log.FAIL + "Fail" + Log.OKBLUE + "]")
        raise SiteError("download WordPress core failed")

    Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")

    if not (data['wo_db_name'] and data['wo_db_user'] and data['wo_db_pass']):
        data = setupdatabase(self, data)
    if prompt_wpprefix == 'True' or prompt_wpprefix == 'true':
        try:
            wo_wp_prefix = input('Enter the WordPress table prefix [wp_]: ')
            while not re.match('^[A-Za-z0-9_]*$', wo_wp_prefix):
                Log.warn(self, "table prefix can only "
                         "contain numbers, letters, and underscores")
                wo_wp_prefix = input('Enter the WordPress table prefix [wp_]: '
                                     )
        except EOFError:
            raise SiteError("input table prefix failed")

    if not wo_wp_prefix:
        wo_wp_prefix = 'wp_'

    # Modify wp-config.php & move outside the webroot

    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))
    Log.debug(self, "Setting up wp-config file")
    if not data['multisite']:
        Log.debug(self, "Generating wp-config for WordPress Single site")
        Log.debug(self, "/bin/bash -c \"{0} --allow-root "
                  .format(WOVariables.wo_wpcli_path) +
                  "config create " +
                  "--dbname=\'{0}\' --dbprefix=\'{1}\' --dbuser=\'{2}\' "
                  "--dbhost=\'{3}\' "
                  .format(data['wo_db_name'], wo_wp_prefix,
                          data['wo_db_user'], data['wo_db_host']) +
                  "--dbpass=\'{0}\' "
                  "--extra-php<<PHP \n {1}\nPHP\""
                  .format(data['wo_db_pass'],
                          "\n\ndefine(\'WP_DEBUG\', false);"))
        try:
            if WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root"
                                    .format(WOVariables.wo_wpcli_path) +
                                    " config create " +
                                    "--dbname=\'{0}\' --dbprefix=\'{1}\' "
                                    "--dbuser=\'{2}\' --dbhost=\'{3}\' "
                                    .format(data['wo_db_name'], wo_wp_prefix,
                                            data['wo_db_user'],
                                            data['wo_db_host']
                                            ) +
                                    "--dbpass=\'{0}\' "
                                    "--extra-php<<PHP \n"
                                    "\n{1}\nPHP\""
                                    .format(data['wo_db_pass'],
                                            "\ndefine(\'WP_DEBUG\', false);"),
                                    log=False
                                    ):
                pass
            else:
                raise SiteError("generate wp-config failed for wp single site")
        except CommandExecutionError:
            raise SiteError("generate wp-config failed for wp single site")
    else:
        Log.debug(self, "Generating wp-config for WordPress multisite")
        Log.debug(self, "/bin/bash -c \"{0} --allow-root "
                  .format(WOVariables.wo_wpcli_path) +
                  "config create " +
                  "--dbname=\'{0}\' --dbprefix=\'{1}\' --dbhost=\'{2}\' "
                  .format(data['wo_db_name'],
                          wo_wp_prefix, data['wo_db_host']) +
                  "--dbuser=\'{0}\' --dbpass=\'{1}\' "
                  "--extra-php<<PHP \n {2} {3} {4} \nPHP\""
                  .format(data['wo_db_user'], data['wo_db_pass'],
                          "\ndefine(\'WPMU_ACCEL_REDIRECT\',"
                          " true);",
                          "\ndefine(\'CONCATENATE_SCRIPTS\',"
                          " false);",
                          "\n\ndefine(\'WP_DEBUG\', false);"))
        try:
            if WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root"
                                    .format(WOVariables.wo_wpcli_path) +
                                    " config create " +
                                    "--dbname=\'{0}\' --dbprefix=\'{1}\' "
                                    "--dbhost=\'{2}\' "
                                    .format(data['wo_db_name'], wo_wp_prefix,
                                            data['wo_db_host']) +
                                    "--dbuser=\'{0}\' --dbpass=\'{1}\' "
                                    "--extra-php<<PHP \n "
                                    "\n{2} {3}\nPHP\""
                                    .format(data['wo_db_user'],
                                            data['wo_db_pass'],
                                            "\ndefine(\'WPMU_ACCEL_REDIRECT\',"
                                            " true);",
                                            "\ndefine(\'WP_DEBUG\', false);"),
                                    log=False
                                    ):
                pass
            else:
                raise SiteError("generate wp-config failed for wp multi site")
        except CommandExecutionError:
            raise SiteError("generate wp-config failed for wp multi site")

    try:

        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set WP_CACHE_KEY_SALT "
                             "\'{0}:\'\"".format(wo_domain_name))

        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set WP_MEMORY_LIMIT "
                             "\'128M\'\"")
        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set WP_MAX_MEMORY_LIMIT "
                             "\'256M\'\"")
        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set CONCATENATE_SCRIPTS "
                             "false --raw\"")
        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set WP_POST_REVISIONS "
                             "\'10\'\"")
        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set MEDIA_TRASH "
                             "true --raw\"")
        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set EMPTY_TRASH_DAYS "
                             "\'15\'\"")
        WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "config set WP_AUTO_UPDATE_CORE "
                             "minor\"")

    except CommandExecutionError as e:
        Log.debug(self, str(e))
        Log.error(self, "Unable to define extra variable in wp-config.php")

    # WOFileUtils.mvfile(self, os.getcwd()+'/wp-config.php',
    #                   os.path.abspath(os.path.join(os.getcwd(), os.pardir)))

    try:
        import shutil

        Log.debug(self, "Moving file from {0} to {1}".format(os.getcwd(
        )+'/wp-config.php', os.path.abspath(os.path.join(os.getcwd(),
                                                         os.pardir))))
        shutil.move(os.getcwd()+'/wp-config.php',
                    os.path.abspath(os.path.join(os.getcwd(), os.pardir)))
    except Exception as e:
        Log.debug(self, str(e))
        Log.error(self, 'Unable to move file from {0} to {1}'
                  .format(os.getcwd()+'/wp-config.php',
                          os.path.abspath(os.path.join(os.getcwd(),
                                                       os.pardir))), False)
        raise SiteError("Unable to move wp-config.php")

    if not wo_wp_user:
        wo_wp_user = WOVariables.wo_user
        while not wo_wp_user:
            Log.warn(self, "Username can have only alphanumeric"
                     "characters, spaces, underscores, hyphens,"
                     "periods and the @ symbol.")
            try:
                wo_wp_user = input('Enter WordPress username: ')
            except EOFError:
                raise SiteError("input WordPress username failed")
    if not wo_wp_pass:
        wo_wp_pass = wo_random_pass

    if not wo_wp_email:
        wo_wp_email = WOVariables.wo_email
        while not wo_wp_email:
            try:
                wo_wp_email = input('Enter WordPress email: ')
            except EOFError:
                raise SiteError("input WordPress username failed")

    try:
        while not re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$",
                           wo_wp_email):
            Log.info(self, "EMail not Valid in config, "
                     "Please provide valid email id")
            wo_wp_email = input("Enter your email: ")
    except EOFError:
        raise SiteError("input WordPress user email failed")

    Log.debug(self, "Setting up WordPress tables")

    if not data['multisite']:
        Log.debug(self, "Creating tables for WordPress Single site")
        Log.debug(self, "{0} --allow-root core install "
                  .format(WOVariables.wo_wpcli_path) +
                  "--url=\'{0}\' --title=\'{0}\' --admin_name=\'{1}\' "
                  .format(data['www_domain'], wo_wp_user) +
                  "--admin_password= --admin_email=\'{1}\'"
                  .format(wo_wp_pass, wo_wp_email))
        try:
            if WOShellExec.cmd_exec(self, "{0} --allow-root core "
                                    .format(WOVariables.wo_wpcli_path) +
                                    "install --url=\'{0}\' --title=\'{0}\' "
                                    "--admin_name=\'{1}\' "
                                    .format(data['www_domain'], wo_wp_user) +
                                    "--admin_password=\'{0}\' "
                                    "--admin_email=\'{1}\'"
                                    .format(wo_wp_pass, wo_wp_email),
                                    log=False):
                pass
            else:
                raise SiteError(
                    "setup WordPress tables failed for single site")
        except CommandExecutionError:
            raise SiteError("setup WordPress tables failed for single site")
    else:
        Log.debug(self, "Creating tables for WordPress multisite")
        Log.debug(self, "{0} --allow-root "
                  .format(WOVariables.wo_wpcli_path) +
                  "core multisite-install "
                  "--url=\'{0}\' --title=\'{0}\' --admin_name=\'{1}\' "
                  .format(data['www_domain'], wo_wp_user) +
                  "--admin_password= --admin_email=\'{1}\' "
                  "{subdomains}"
                  .format(wo_wp_pass, wo_wp_email,
                          subdomains='--subdomains'
                          if not data['wpsubdir'] else ''))
        try:
            if WOShellExec.cmd_exec(self, "{0} --allow-root "
                                    .format(WOVariables.wo_wpcli_path) +
                                    "core multisite-install "
                                    "--url=\'{0}\' --title=\'{0}\' "
                                    "--admin_name=\'{1}\' "
                                    .format(data['www_domain'], wo_wp_user) +
                                    "--admin_password=\'{0}\' "
                                    "--admin_email=\'{1}\' "
                                    "{subdomains}"
                                    .format(wo_wp_pass, wo_wp_email,
                                            subdomains='--subdomains'
                                            if not data['wpsubdir'] else ''),
                                    log=False):
                pass
            else:
                raise SiteError(
                    "setup WordPress tables failed for wp multi site")
        except CommandExecutionError:
            raise SiteError("setup WordPress tables failed for wp multi site")

    Log.debug(self, "Updating WordPress permalink")
    try:
        WOShellExec.cmd_exec(self, " {0} --allow-root "
                             .format(WOVariables.wo_wpcli_path) +
                             "rewrite structure "
                             "/%postname%/")
    except CommandExecutionError as e:
        Log.debug(self, str(e))
        raise SiteError("Update wordpress permalinks failed")

    """Install nginx-helper plugin """
    installwp_plugin(self, 'nginx-helper', data)
    if data['wpfc']:
        plugin_data_object = {"log_level": "INFO",
                              "log_filesize": 5,
                              "enable_purge": 1,
                              "enable_map": "0",
                              "enable_log": 0,
                              "enable_stamp": 1,
                              "purge_homepage_on_new": 1,
                              "purge_homepage_on_edit": 1,
                              "purge_homepage_on_del": 1,
                              "purge_archive_on_new": 1,
                              "purge_archive_on_edit": 1,
                              "purge_archive_on_del": 1,
                              "purge_archive_on_new_comment": 0,
                              "purge_archive_on_deleted_comment": 0,
                              "purge_page_on_mod": 1,
                              "purge_page_on_new_comment": 1,
                              "purge_page_on_deleted_comment": 1,
                              "cache_method": "enable_fastcgi",
                              "purge_method": "get_request",
                              "redis_hostname": "127.0.0.1",
                              "redis_port": "6379",
                              "redis_prefix": "nginx-cache:"}
        plugin_data = json.dumps(plugin_data_object)
        setupwp_plugin(self, "nginx-helper",
                       "rt_wp_nginx_helper_options", plugin_data, data)
    elif data['wpredis']:
        plugin_data_object = {"log_level": "INFO",
                              "log_filesize": 5,
                              "enable_purge": 1,
                              "enable_map": "0",
                              "enable_log": 0,
                              "enable_stamp": 1,
                              "purge_homepage_on_new": 1,
                              "purge_homepage_on_edit": 1,
                              "purge_homepage_on_del": 1,
                              "purge_archive_on_new": 1,
                              "purge_archive_on_edit": 1,
                              "purge_archive_on_del": 1,
                              "purge_archive_on_new_comment": 0,
                              "purge_archive_on_deleted_comment": 0,
                              "purge_page_on_mod": 1,
                              "purge_page_on_new_comment": 1,
                              "purge_page_on_deleted_comment": 1,
                              "cache_method": "enable_redis",
                              "purge_method": "get_request",
                              "redis_hostname": "127.0.0.1",
                              "redis_port": "6379",
                              "redis_prefix": "nginx-cache:"}
        plugin_data = json.dumps(plugin_data_object)
        setupwp_plugin(self, 'nginx-helper',
                       'rt_wp_nginx_helper_options', plugin_data, data)

    """Install Wp Super Cache"""
    if data['wpsc']:
        installwp_plugin(self, 'wp-super-cache', data)

    """Install Redis Cache"""
    if data['wpredis']:
        installwp_plugin(self, 'redis-cache', data)

    """Install Cache-Enabler"""
    if data['wpce']:
        installwp_plugin(self, 'cache-enabler', data)
        plugin_data_object = {"expires": 24,
                              "new_post": 1,
                              "new_comment": 0,
                              "webp": 0,
                              "clear_on_upgrade": 1,
                              "compress": 0,
                              "excl_ids": "",
                              "excl_regexp": "",
                              "excl_cookies": "",
                              "incl_attributes": "",
                              "minify_html": 1}
        plugin_data = json.dumps(plugin_data_object)
        setupwp_plugin(self, 'cache-enabler', 'cache-enabler',
                       plugin_data, data)

    if vhostonly:
        try:
            WOShellExec.cmd_exec(self, "/bin/bash -c \"{0} --allow-root "
                                 .format(WOVariables.wo_wpcli_path) +
                                 "db clean --yes\"")
            WOFileUtils.rm(self, "{0}/htdocs".format(wo_site_webroot))
            WOFileUtils.mkdir(self, "{0}/htdocs".format(wo_site_webroot))
            WOFileUtils.chown(self, "{0}/htdocs".format(wo_site_webroot),
                              'www-data', 'www-data')
        except CommandExecutionError:
            raise SiteError("Cleaning WordPress install failed")

    wp_creds = dict(wp_user=wo_wp_user, wp_pass=wo_wp_pass,
                    wp_email=wo_wp_email)

    return(wp_creds)


def setupwordpressnetwork(self, data):
    wo_site_webroot = data['webroot']
    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))
    Log.info(self, "Setting up WordPress Network \t", end='')
    try:
        if WOShellExec.cmd_exec(self, 'wp --allow-root core multisite-convert'
                                ' --title=\'{0}\' {subdomains}'
                                .format(data['www_domain'],
                                        subdomains='--subdomains'
                                        if not data['wpsubdir'] else '')):
            pass
        else:
            Log.info(self, "[" + Log.ENDC + Log.FAIL +
                     "Fail" + Log.OKBLUE + "]")
            raise SiteError("setup WordPress network failed")

    except CommandExecutionError as e:
        Log.debug(self, str(e))
        Log.info(self, "[" + Log.ENDC + Log.FAIL + "Fail" + Log.OKBLUE + "]")
        raise SiteError("setup WordPress network failed")
    Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")


def installwp_plugin(self, plugin_name, data):
    wo_site_webroot = data['webroot']
    Log.info(self, "Installing plugin {0}, please wait..."
             .format(plugin_name))
    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))
    try:
        WOShellExec.cmd_exec(self, "{0} plugin "
                             .format(WOVariables.wo_wpcli_path) +
                             "--allow-root install "
                             "{0}".format(plugin_name))
    except CommandExecutionError as e:
        Log.debug(self, str(e))
        raise SiteError("plugin installation failed")

    try:
        WOShellExec.cmd_exec(self, "{0} plugin "
                             .format(WOVariables.wo_wpcli_path) +
                             "--allow-root activate "
                             "{0} {na}"
                             .format(plugin_name,
                                     na='--network' if data['multisite']
                                     else ''
                                     ))
    except CommandExecutionError as e:
        Log.debug(self, "{0}".format(e))
        raise SiteError("plugin activation failed")

    return 1


def uninstallwp_plugin(self, plugin_name, data):
    wo_site_webroot = data['webroot']
    Log.debug(self, "Uninstalling plugin {0}, please wait..."
              .format(plugin_name))
    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))
    Log.info(self, "Uninstalling plugin {0}, please wait..."
             .format(plugin_name))
    try:
        WOShellExec.cmd_exec(self, "{0} plugin "
                             .format(WOVariables.wo_wpcli_path) +
                             "--allow-root deactivate "
                             "{0}".format(plugin_name))

        WOShellExec.cmd_exec(self, "{0} plugin "
                             .format(WOVariables.wo_wpcli_path) +
                             "--allow-root uninstall "
                             "{0}".format(plugin_name))
    except CommandExecutionError as e:
        Log.debug(self, "{0}".format(e))
        raise SiteError("plugin uninstall failed")


def setupwp_plugin(self, plugin_name, plugin_option, plugin_data, data):
    wo_site_webroot = data['webroot']
    Log.info(self, "Setting plugin {0}, please wait..."
             .format(plugin_name))
    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))

    if not data['multisite']:
        try:
            WOShellExec.cmd_exec(self, "{0} "
                                 .format(WOVariables.wo_wpcli_path) +
                                 "--allow-root option update "
                                 "{0} \'{1}\' --format=json"
                                 .format(plugin_option, plugin_data))
        except CommandExecutionError as e:
            Log.debug(self, "{0}".format(e))
            raise SiteError("plugin setup failed")
    else:
        try:
            WOShellExec.cmd_exec(self, "{0} "
                                 .format(WOVariables.wo_wpcli_path) +
                                 "--allow-root network meta update 1 "
                                 "{0} \'{1}\' --format=json"
                                 .format(plugin_option, plugin_data
                                         ))
        except CommandExecutionError as e:
            Log.debug(self, "{0}".format(e))
            raise SiteError("plugin setup failed")


def setwebrootpermissions(self, webroot):
    Log.debug(self, "Setting up permissions")
    try:
        WOFileUtils.findBrokenSymlink(self, '/var/www/')
        WOFileUtils.chown(self, webroot, WOVariables.wo_php_user,
                          WOVariables.wo_php_user, recursive=True)
    except Exception as e:
        Log.debug(self, str(e))
        raise SiteError("problem occured while setting up webroot permissions")


def sitebackup(self, data):
    wo_site_webroot = data['webroot']
    backup_path = wo_site_webroot + '/backup/{0}'.format(WOVariables.wo_date)
    if not WOFileUtils.isexist(self, backup_path):
        WOFileUtils.mkdir(self, backup_path)
    Log.info(self, "Backup location : {0}".format(backup_path))
    WOFileUtils.copyfile(self, '/etc/nginx/sites-available/{0}'
                         .format(data['site_name']), backup_path)

    if data['currsitetype'] in ['html', 'php', 'proxy', 'mysql']:
        if data['php73'] is True and not data['wp']:
            Log.info(self, "Backing up Webroot \t\t", end='')
            WOFileUtils.copyfiles(self, wo_site_webroot +
                                  '/htdocs', backup_path + '/htdocs')
            Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")
        else:
            Log.info(self, "Backing up Webroot \t\t", end='')
            WOFileUtils.mvfile(self, wo_site_webroot + '/htdocs', backup_path)
            Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")

    configfiles = glob.glob(wo_site_webroot + '/*-config.php')
    if not configfiles:
        # search for wp-config.php inside htdocs/
        Log.debug(self, "Config files not found in {0}/ "
                  .format(wo_site_webroot))
        if data['currsitetype'] in ['mysql']:
            pass
        else:
            Log.debug(self, "Searching wp-config.php in {0}/htdocs/ "
                      .format(wo_site_webroot))
            configfiles = glob.glob(wo_site_webroot + '/htdocs/wp-config.php')

    # if configfiles and WOFileUtils.isexist(self, configfiles[0]):
    #     wo_db_name = (WOFileUtils.grep(self, configfiles[0],
    #                   'DB_NAME').split(',')[1]
    #                   .split(')')[0].strip().replace('\'', ''))
    if data['wo_db_name']:
        Log.info(self, 'Backing up database \t\t', end='')
        try:
            if not WOShellExec.cmd_exec(self, "mysqldump --single-transaction "
                                        "{0} | pigz -9 -p\"$(nproc)\" "
                                        "> {1}/{0}.gz"
                                        .format(data['wo_db_name'],
                                                backup_path)):
                Log.info(self,
                         "[" + Log.ENDC + Log.FAIL + "Fail" + Log.OKBLUE + "]")
                raise SiteError("mysqldump failed to backup database")
        except CommandExecutionError as e:
            Log.debug(self, str(e))
            Log.info(self, "[" + Log.ENDC + "Fail" + Log.OKBLUE + "]")
            raise SiteError("mysqldump failed to backup database")
        Log.info(self, "[" + Log.ENDC + "Done" + Log.OKBLUE + "]")
        # move wp-config.php/wo-config.php to backup
        if data['currsitetype'] in ['mysql', 'proxy']:
            if data['php73'] is True and not data['wp']:
                WOFileUtils.copyfile(self, configfiles[0], backup_path)
            else:
                WOFileUtils.mvfile(self, configfiles[0], backup_path)
        else:
            WOFileUtils.copyfile(self, configfiles[0], backup_path)


def site_package_check(self, stype):
    apt_packages = []
    packages = []
    stack = WOStackController()
    stack.app = self.app
    if stype in ['html', 'proxy', 'php', 'mysql', 'wp', 'wpsubdir',
                 'wpsubdomain', 'php73']:
        Log.debug(self, "Setting apt_packages variable for Nginx")

        # Check if server has nginx-custom package
        if not (WOAptGet.is_installed(self, 'nginx-custom') or
                WOAptGet.is_installed(self, 'nginx-mainline')):
            # check if Server has nginx-plus installed
            if WOAptGet.is_installed(self, 'nginx-plus'):
                # do something
                # do post nginx installation configuration
                Log.info(self, "NGINX PLUS Detected ...")
                apt = ["nginx-plus"] + WOVariables.wo_nginx
                # apt_packages = apt_packages + WOVariables.wo_nginx
                stack.post_pref(self, apt, packages)
            elif WOAptGet.is_installed(self, 'nginx'):
                Log.info(self, "WordOps detected a previously"
                               "installed Nginx package. "
                               "It may or may not have required modules. "
                               "\nIf you need help, please create an issue at "
                               "https://github.com/WordOps/WordOps/issues/ \n")
                apt = ["nginx"] + WOVariables.wo_nginx
                # apt_packages = apt_packages + WOVariables.wo_nginx
                post_pref(self, apt, packages)
            else:
                apt_packages = apt_packages + WOVariables.wo_nginx
        else:
            # Fix for Nginx white screen death
            if not WOFileUtils.grep(self, '/etc/nginx/fastcgi_params',
                                    'SCRIPT_FILENAME'):
                with open('/etc/nginx/fastcgi_params', encoding='utf-8',
                          mode='a') as wo_nginx:
                    wo_nginx.write('fastcgi_param \tSCRIPT_FILENAME '
                                   '\t$request_filename;\n')

    if self.app.pargs.php and self.app.pargs.php73:
        Log.error(
            self, "Error: two different PHP versions cannot be "
                  "combined within the same WordOps site")

    if not self.app.pargs.php73 and stype in ['php', 'mysql', 'wp', 'wpsubdir',
                                              'wpsubdomain']:
        Log.debug(self, "Setting apt_packages variable for PHP 7.2")
        if not WOAptGet.is_installed(self, 'php7.2-fpm'):
            if not WOAptGet.is_installed(self, 'php7.3-fpm'):
                apt_packages = apt_packages + WOVariables.wo_php + \
                    WOVariables.wo_php_extra
            else:
                apt_packages = apt_packages + WOVariables.wo_php

    if self.app.pargs.php73 and stype in ['mysql', 'wp',
                                          'wpsubdir', 'wpsubdomain']:
        Log.debug(self, "Setting apt_packages variable for PHP 7.3")
        if not WOAptGet.is_installed(self, 'php7.3-fpm'):
            if not WOAptGet.is_installed(self, 'php7.2-fpm'):
                apt_packages = apt_packages + WOVariables.wo_php + \
                    WOVariables.wo_php73 + WOVariables.wo_php_extra
            else:
                apt_packages = apt_packages + WOVariables.wo_php73

    if stype in ['mysql', 'wp', 'wpsubdir', 'wpsubdomain']:
        Log.debug(self, "Setting apt_packages variable for MySQL")
        if not WOShellExec.cmd_exec(self, "/usr/bin/mysqladmin ping"):
            apt_packages = apt_packages + WOVariables.wo_mysql

    if stype in ['wp', 'wpsubdir', 'wpsubdomain']:
        Log.debug(self, "Setting packages variable for WP-CLI")
        if not WOShellExec.cmd_exec(self, "command -v wp"):
            packages = packages + [["https://github.com/wp-cli/wp-cli/"
                                    "releases/download/v{0}/"
                                    "wp-cli-{0}.phar"
                                    .format(WOVariables.wo_wp_cli),
                                    "/usr/local/bin/wp", "WP-CLI"]]
    if self.app.pargs.wpredis:
        Log.debug(self, "Setting apt_packages variable for redis")
        if not WOAptGet.is_installed(self, 'redis-server'):
            apt_packages = apt_packages + WOVariables.wo_redis

    if self.app.pargs.php73:
        Log.debug(self, "Setting apt_packages variable for PHP 7.3")
        if not WOAptGet.is_installed(self, 'php7.3-fpm'):
            if not WOAptGet.is_installed(self, 'php7.2-fpm'):
                apt_packages = apt_packages + WOVariables.wo_php + \
                    WOVariables.wo_php73 + WOVariables.wo_php_extra
            else:
                apt_packages = apt_packages + WOVariables.wo_php73

    return(stack.install(apt_packages=apt_packages, packages=packages,
                         disp_msg=False))


def updatewpuserpassword(self, wo_domain, wo_site_webroot):

    wo_wp_user = ''
    wo_wp_pass = ''
    WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))

    # Check if wo_domain is wordpress install
    try:
        is_wp = WOShellExec.cmd_exec(self, "wp --allow-root core"
                                     " version")
    except CommandExecutionError as e:
        Log.debug(self, "{0}".format(e))
        raise SiteError("is WordPress site? check command failed ")

    # Exit if wo_domain is not wordpress install
    if not is_wp:
        Log.error(self, "{0} does not seem to be a WordPress site"
                  .format(wo_domain))

    try:
        wo_wp_user = input("Provide WordPress user name [admin]: ")
    except Exception as e:
        Log.debug(self, str(e))
        Log.error(self, "\nCould not update password")

    if wo_wp_user == "?":
        Log.info(self, "Fetching WordPress user list")
        try:
            WOShellExec.cmd_exec(self, "wp --allow-root user list "
                                 "--fields=user_login | grep -v user_login")
        except CommandExecutionError as e:
            Log.debug(self, "{0}".format(e))
            raise SiteError("fetch wp userlist command failed")

    if not wo_wp_user:
        wo_wp_user = 'admin'

    try:
        is_user_exist = WOShellExec.cmd_exec(self, "wp --allow-root user list "
                                             "--fields=user_login | grep {0}$ "
                                             .format(wo_wp_user))
    except CommandExecutionError as e:
        Log.debug(self, "{0}".format(e))
        raise SiteError("if wp user exists check command failed")

    if is_user_exist:
        try:
            wo_wp_pass = getpass.getpass(prompt="Provide password for "
                                         "{0} user: "
                                         .format(wo_wp_user))

            while not wo_wp_pass:
                wo_wp_pass = getpass.getpass(prompt="Provide password for "
                                             "{0} user: "
                                             .format(wo_wp_user))
        except Exception as e:
            Log.debug(self, str(e))
            raise SiteError("failed to read password input ")

        try:
            WOShellExec.cmd_exec(self, "wp --allow-root user update {0}"
                                 "  --user_pass={1}"
                                 .format(wo_wp_user, wo_wp_pass))
        except CommandExecutionError as e:
            Log.debug(self, str(e))
            raise SiteError("wp user password update command failed")
        Log.info(self, "Password updated successfully")

    else:
        Log.error(self, "Invalid WordPress user {0} for {1}."
                  .format(wo_wp_user, wo_domain))


def display_cache_settings(self, data):
    if data['wpsc']:
        if data['multisite']:
            Log.info(self, "Configure WPSC:"
                     "\t\thttp://{0}/wp-admin/network/settings.php?"
                     "page=wpsupercache"
                     .format(data['site_name']))
        else:
            Log.info(self, "Configure WPSC:"
                     "\t\thttp://{0}/wp-admin/options-general.php?"
                     "page=wpsupercache"
                     .format(data['site_name']))

    if data['wpredis']:
        if data['multisite']:
            Log.info(self, "Configure redis-cache:"
                     "\thttp://{0}/wp-admin/network/settings.php?"
                     "page=redis-cache".format(data['site_name']))
        else:
            Log.info(self, "Configure redis-cache:"
                     "\thttp://{0}/wp-admin/options-general.php?"
                     "page=redis-cache".format(data['site_name']))
        Log.info(self, "Object Cache:\t\tEnable")

    if data['wpfc']:
        if data['multisite']:
            Log.info(self, "Nginx-Helper configuration :"
                     "\thttp://{0}/wp-admin/network/settings.php?"
                     "page=nginx".format(data['site_name']))
        else:
            Log.info(self, "Nginx-Helper configuration :"
                     "\thttp://{0}/wp-admin/options-general.php?"
                     "page=nginx".format(data['site_name']))

    if data['wpce']:
        if data['multisite']:
            Log.info(self, "Nginx-Helper configuration :"
                     "\thttp://{0}/wp-admin/network/settings.php?"
                     "page=cache-enabler".format(data['site_name']))
        else:
            Log.info(self, "Nginx-Helper configuration :"
                     "\thttp://{0}/wp-admin/options-general.php?"
                     "page=cache-enabler".format(data['site_name']))


def logwatch(self, logfiles):
    import zlib
    import base64
    import time
    from wo.core import logwatch

    def callback(filename, lines):
        for line in lines:
            if line.find(':::') == -1:
                print(line)
            else:
                data = line.split(':::')
                try:
                    print(data[0], data[1],
                          zlib.decompress(base64.decodestring(data[2])))
                except Exception as e:
                    Log.debug(self, str(e))
                    Log.info(time.time(),
                             'caught exception rendering a new log line in %s'
                             % filename)

    logl = logwatch.LogWatcher(logfiles, callback)
    logl.loop()


def detSitePar(opts):
    """
        Takes dictionary of parsed arguments
        1.returns sitetype and cachetype
        2. raises RuntimeError when wrong combination is used like
            "--wp --wpsubdir" or "--html --wp"
    """
    sitetype, cachetype = '', ''
    typelist = list()
    cachelist = list()
    for key, val in opts.items():
        if val and key in ['html', 'php', 'mysql', 'wp',
                           'wpsubdir', 'wpsubdomain', 'php73']:
            typelist.append(key)
        elif val and key in ['wpfc', 'wpsc', 'wpredis', 'wprocket', 'wpce']:
            cachelist.append(key)

    if len(typelist) > 1 or len(cachelist) > 1:
        if len(cachelist) > 1:
            raise RuntimeError(
                "Could not determine cache type."
                "Multiple cache parameter entered")
        elif False not in [x in ('php', 'mysql', 'html') for x in typelist]:
            sitetype = 'mysql'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('php73', 'mysql', 'html') for x in typelist]:
            sitetype = 'mysql'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('php', 'mysql') for x in typelist]:
            sitetype = 'mysql'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('php73', 'mysql') for x in typelist]:
            sitetype = 'mysql'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('html', 'mysql') for x in typelist]:
            sitetype = 'mysql'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('php', 'html') for x in typelist]:
            sitetype = 'php'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('php73', 'html') for x in typelist]:
            sitetype = 'php73'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('wp', 'wpsubdir') for x in typelist]:
            sitetype = 'wpsubdir'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('wp', 'wpsubdomain') for x in typelist]:
            sitetype = 'wpsubdomain'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('wp', 'php73') for x in typelist]:
            sitetype = 'wp'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('wpsubdir', 'php73') for x in typelist]:
            sitetype = 'wpsubdir'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        elif False not in [x in ('wpsubdomain', 'php73') for x in typelist]:
            sitetype = 'wpsubdomain'
            if not cachelist:
                cachetype = 'basic'
            else:
                cachetype = cachelist[0]
        else:
            raise RuntimeError("could not determine site and cache type")
    else:
        if not typelist and not cachelist:
            sitetype = None
            cachetype = None
        elif (not typelist or "php73" in typelist) and cachelist:
            sitetype = 'wp'
            cachetype = cachelist[0]
        elif typelist and (not cachelist):
            sitetype = typelist[0]
            cachetype = 'basic'
        else:
            sitetype = typelist[0]
            cachetype = cachelist[0]

    return (sitetype, cachetype)


def generate_random_pass():
    wo_random10 = (''.join(random.sample(string.ascii_uppercase +
                                         string.ascii_lowercase +
                                         string.digits, 24)))
    return wo_random10


def generate_random():
    wo_random10 = (''.join(random.sample(string.ascii_uppercase +
                                         string.ascii_lowercase +
                                         string.digits, 8)))
    return wo_random10


def deleteDB(self, dbname, dbuser, dbhost, exit=True):
    try:
        # Check if Database exists
        try:
            if WOMysql.check_db_exists(self, dbname):
                # Drop database if exists
                Log.debug(self, "dropping database `{0}`".format(dbname))
                WOMysql.execute(self,
                                "drop database `{0}`".format(dbname),
                                errormsg='Unable to drop database {0}'
                                .format(dbname))
        except StatementExcecutionError as e:
            Log.debug(self, str(e))
            Log.debug(self, "drop database failed")
            Log.info(self, "Database {0} not dropped".format(dbname))

        except MySQLConnectionError as e:
            Log.debug(self, str(e))
            Log.debug(self, "Mysql Connection problem occured")

        if dbuser != 'root':
            Log.debug(self, "dropping user `{0}`".format(dbuser))
            try:
                WOMysql.execute(self,
                                "drop user `{0}`@`{1}`"
                                .format(dbuser, dbhost))
            except StatementExcecutionError as e:
                Log.debug(self, str(e))
                Log.debug(self, "drop database user failed")
                Log.info(self, "Database {0} not dropped".format(dbuser))
            try:
                WOMysql.execute(self, "flush privileges")
            except StatementExcecutionError as e:
                Log.debug(self, str(e))
                Log.debug(self, "drop database failed")
                Log.info(self, "Database {0} not dropped".format(dbname))
    except Exception as e:
        Log.debug(self, str(e))
        Log.error(self, "Error occured while deleting database", exit)


def deleteWebRoot(self, webroot):
    # do some preprocessing before proceeding
    webroot = webroot.strip()
    if (webroot == "/var/www/" or webroot == "/var/www" or
            webroot == "/var/www/.." or webroot == "/var/www/."):
        Log.debug(self, "Tried to remove {0}, but didn't remove it"
                  .format(webroot))
        return False

    if os.path.isdir(webroot):
        Log.debug(self, "Removing {0}".format(webroot))
        WOFileUtils.rm(self, webroot)
        return True
    Log.debug(self, "{0} does not exist".format(webroot))
    return False


def removeNginxConf(self, domain):
    if os.path.isfile('/etc/nginx/sites-available/{0}'
                      .format(domain)):
        Log.debug(self, "Removing Nginx configuration")
        WOFileUtils.rm(self, '/etc/nginx/sites-enabled/{0}'
                       .format(domain))
        WOFileUtils.rm(self, '/etc/nginx/sites-available/{0}'
                       .format(domain))
        WOService.reload_service(self, 'nginx')
        WOGit.add(self, ["/etc/nginx"],
                  msg="Deleted {0} "
                  .format(domain))


def removeAcmeConf(self, domain):
    sslconf = ("/var/www/{0}/conf/nginx/ssl.conf"
               .format(domain))
    sslforce = ("/etc/nginx/conf.d/force-ssl-{0}.conf"
                .format(domain))
    if os.path.isdir('/etc/letsencrypt/renewal/{0}_ecc'
                     .format(domain)):
        Log.info(self, "Removing Acme configuration")
        Log.debug(self, "Removing Acme configuration")
        try:
            WOShellExec.cmd_exec(self, "/etc/letsencrypt/acme.sh "
                                       "--config-home "
                                       "'/etc/letsencrypt/config' "
                                       "--remove "
                                       "-d {0} --ecc"
                                       .format(domain))
        except CommandExecutionError as e:
            Log.debug(self, "{0}".format(e))
            Log.error(self, "Cert removal failed")

        WOFileUtils.rm(self, '{0}/{1}_ecc'
                       .format(WOVariables.wo_ssl_archive, domain))
        WOFileUtils.rm(self, '{0}/{1}'
                       .format(WOVariables.wo_ssl_live, domain))
        WOFileUtils.rm(self, '{0}'.format(sslconf))
        WOFileUtils.rm(self, '{0}.disabled'.format(sslconf))
        WOFileUtils.rm(self, '{0}'.format(sslforce))
        WOFileUtils.rm(self, '{0}.disabled'
                       .format(sslforce))
        WOFileUtils.rm(self, '/etc/letsencrypt/shared/{0}.conf'
                       .format(domain))

        # find all broken symlinks
        sympath = "/var/www"
        WOFileUtils.findBrokenSymlink(self, sympath)

    else:
        if os.path.islink("{0}".format(sslconf)):
            WOFileUtils.remove_symlink(self, "{0}".format(sslconf))
            WOFileUtils.rm(self, '{0}'.format(sslforce))

    if WOFileUtils.grepcheck(self, '/var/www/22222/conf/nginx/ssl.conf',
                             '{0}'.format(domain)):
        Log.info(self, "Setting back default certificate for WordOps backend")
        with open("/var/www/22222/conf/nginx/"
                  "ssl.conf", "w") as ssl_conf_file:
            ssl_conf_file.write("ssl_certificate "
                                "/var/www/22222/cert/22222.crt;\n"
                                "ssl_certificate_key "
                                "/var/www/22222/cert/22222.key;\n")
    WOGit.add(self, ["/etc/letsencrypt"],
              msg="Deleted {0} "
              .format(domain))
    WOService.restart_service(self, "nginx")


def site_url_https(self, domain):
    if os.path.isfile('/var/www/{0}/wp-config.php'.format(domain)):
        wo_site_webroot = ('/var/www/{0}'.format(domain))
        Log.info(self, "Checking if site url already "
                 "use https, please wait...")
        WOFileUtils.chdir(self, '{0}/htdocs/'.format(wo_site_webroot))
        wo_siteurl = \
            WOShellExec.cmd_exec_stdout(self,
                                        "{0} option get siteurl "
                                        .format(WOVariables.wo_wpcli_path) +
                                        "--allow-root --quiet")
        test_url = re.split(":", wo_siteurl)
        if not (test_url[0] == 'https'):
            try:
                WOShellExec.cmd_exec(self, "{0} option update siteurl "
                                     "\'https://{1}\' --allow-root".format(
                                         WOVariables.wo_wpcli_path, domain))
                WOShellExec.cmd_exec(self, "{0} option update home "
                                     "\'https://{1}\' --allow-root".format(
                                         WOVariables.wo_wpcli_path, domain))
            except CommandExecutionError as e:
                Log.debug(self, "{0}".format(e))
                raise SiteError("migration to https failed")
            Log.info(
                self, "Site address updated "
                "successfully to https://{0}".format(domain))
        else:
            Log.info(
                self, "Site address was already using https")


def doCleanupAction(self, domain='', webroot='', dbname='', dbuser='',
                    dbhost=''):
    """
       Removes the nginx configuration and database for the domain provided.
       doCleanupAction(self, domain='sitename', webroot='',
                       dbname='', dbuser='', dbhost='')
    """
    if domain:
        if os.path.isfile('/etc/nginx/sites-available/{0}'
                          .format(domain)):
            removeNginxConf(self, domain)
        if os.path.isdir('/etc/letsencrypt/renewal/{0}_ecc'
                         .format(domain)):
            removeAcmeConf(self, domain)

    if webroot:
        deleteWebRoot(self, webroot)

    if dbname:
        if not dbuser:
            raise SiteError("dbuser not provided")
        if not dbhost:
            raise SiteError("dbhost not provided")
        deleteDB(self, dbname, dbuser, dbhost)

# setup letsencrypt for domain + www.domain


def setupLetsEncrypt(self, wo_domain_name, subdomain=False, wildcard=False,
                     wo_dns=False, wo_acme_dns='dns_cf', backend=False):

    if os.path.isfile("/etc/letsencrypt/"
                      "renewal/{0}_ecc/"
                      "fullchain.cer".format(wo_domain_name)):
        Log.debug(self, "Let's Encrypt certificate "
                  "found for the domain: {0}"
                  .format(wo_domain_name))
        ssl = archivedCertificateHandle(self, wo_domain_name)
    else:
        keylenght = "{0}".format(self.app.config.get('letsencrypt',
                                                     'keylength'))
        wo_acme_exec = ("/etc/letsencrypt/acme.sh --config-home "
                        "'/etc/letsencrypt/config'")
        if wo_dns:
            acme_mode = "--dns {0}".format(wo_acme_dns)
            validation_mode = "DNS with {0}".format(wo_acme_dns)
            Log.debug(
                self, "Validation : DNS mode with {0}".format(wo_acme_dns))
        else:
            acme_mode = "-w /var/www/html"
            validation_mode = "Subdomain Webroot challenge"
            Log.debug(self, "Validation : Webroot mode")
        if subdomain:
            Log.info(self, "Issuing subdomain SSL cert with acme.sh")
            Log.info(self, "Validation mode : {0}".format(validation_mode))
            ssl = WOShellExec.cmd_exec(self, "{0} ".format(wo_acme_exec) +
                                       "--issue "
                                       "-d {0} {1} "
                                       "-k {2} -f"
                                       .format(wo_domain_name,
                                               acme_mode,
                                               keylenght))
        elif wildcard:
            Log.info(self, "Issuing Wildcard SSL cert with acme.sh")
            Log.info(self, "Validation mode : {0}".format(validation_mode))
            ssl = WOShellExec.cmd_exec(self, "{0} ".format(wo_acme_exec) +
                                       "--issue "
                                       "-d {0} -d '*.{0}' --dns {1} "
                                       "-k {2} -f"
                                       .format(wo_domain_name,
                                               wo_acme_dns,
                                               keylenght))
        else:
            Log.info(self, "Issuing domain SSL cert with acme.sh")
            Log.info(self, "Validation mode : {0}".format(validation_mode))
            ssl = WOShellExec.cmd_exec(self, "{0} ".format(wo_acme_exec) +
                                       "--issue "
                                       "-d {0} -d www.{0} {1} "
                                       "-k {2} -f"
                                       .format(wo_domain_name,
                                               acme_mode, keylenght))
    if ssl:
        Log.info(self, "Deploying SSL cert with acme.sh")
        Log.debug(self, "Cert deployment for domain: {0}"
                  .format(wo_domain_name))
        try:

            WOShellExec.cmd_exec(self, "mkdir -p {0}/{1} && "
                                 "/etc/letsencrypt/acme.sh "
                                 "--config-home "
                                 "'/etc/letsencrypt/config' "
                                 "--install-cert -d {1} --ecc "
                                 "--cert-file {0}/{1}/cert.pem "
                                 "--key-file {0}/{1}/key.pem "
                                 "--fullchain-file "
                                 "{0}/{1}/fullchain.pem "
                                 "--ca-file {0}/{1}/ca.pem "
                                 "--reloadcmd "
                                 "\"nginx -t && "
                                 "service nginx restart\" "
                                 .format(WOVariables.wo_ssl_live,
                                         wo_domain_name))
            Log.info(
                self, "Adding /var/www/{0}/conf/nginx/ssl.conf"
                .format(wo_domain_name))

            sslconf = open("/var/www/{0}/conf/nginx/ssl.conf"
                           .format(wo_domain_name),
                           encoding='utf-8', mode='w')
            sslconf.write("listen 443 ssl http2;\n"
                          "listen [::]:443 ssl http2;\n"
                          "ssl_certificate     {0}/{1}/fullchain.pem;\n"
                          "ssl_certificate_key     {0}/{1}/key.pem;\n"
                          "ssl_trusted_certificate {0}/{1}/ca.pem;\n"
                          "ssl_stapling_verify on;\n"
                          .format(WOVariables.wo_ssl_live, wo_domain_name))
            sslconf.close()
            # updateSiteInfo(self, wo_domain_name, ssl=True)
            if not WOFileUtils.grep(self, '/var/www/22222/conf/nginx/ssl.conf',
                                    '/etc/letsencrypt'):
                Log.info(self, "Securing WordOps backend with {0} certificate"
                         .format(wo_domain_name))
                sslconf = open("/var/www/22222/conf/nginx/ssl.conf",
                               encoding='utf-8', mode='w')
                sslconf.write("ssl_certificate     {0}/{1}/fullchain.pem;\n"
                              "ssl_certificate_key     {0}/{1}/key.pem;\n"
                              "ssl_trusted_certificate {0}/{1}/ca.pem;\n"
                              "ssl_stapling_verify on;\n"
                              .format(WOVariables.wo_ssl_live, wo_domain_name))
                sslconf.close()

            WOGit.add(self, ["/etc/letsencrypt"],
                      msg="Adding letsencrypt folder")

        except IOError as e:
            Log.debug(self, str(e))
            Log.debug(self, "Error occured while generating "
                      "ssl.conf")
    else:
        Log.error(self, "Unable to install certificate", False)
        Log.error(self, "Please make sure that your site is pointed to \n"
                  "same server on which "
                  "you are running Let\'s Encrypt Client "
                  "\n to allow it to verify the site automatically.")

# check if a wildcard exist to secure a new subdomain


def checkWildcardExist(self, wo_domain_name):

    wo_acme_exec = ("/etc/letsencrypt/acme.sh --config-home "
                    "'/etc/letsencrypt/config'")
    # export certificates list from acme.sh
    WOShellExec.cmd_exec(self, "{0} ".format(wo_acme_exec) +
                         "--list --listraw > /var/lib/wo/cert.csv")

    # define new csv dialect
    csv.register_dialect('acmeconf', delimiter='|')
    # open file
    certfile = open('/var/lib/wo/cert.csv', mode='r', encoding='utf-8')
    reader = csv.reader(certfile, 'acmeconf')
    wo_wildcard_domain = ("*.{0}".format(wo_domain_name))
    for row in reader:
        if wo_wildcard_domain in row[2]:
            isWildcard = True
            break
        else:
            isWildcard = False
    certfile.close()

    return isWildcard


# copy wildcard certificate to a subdomain


def copyWildcardCert(self, wo_domain_name, wo_root_domain):

    if os.path.isfile("/var/www/{0}/conf/nginx/ssl.conf"
                      .format(wo_root_domain)):
        try:
            if not os.path.isdir("/etc/letsencrypt/shared"):
                WOFileUtils.mkdir(self, "/etc/letsencrypt/shared")
            if not os.path.isfile("/etc/letsencrypt/shared/{0}.conf"
                                  .format(wo_root_domain)):
                WOFileUtils.copyfile(self, "/var/www/{0}/conf/nginx/ssl.conf"
                                     .format(wo_root_domain),
                                     "/etc/letsencrypt/shared/{0}.conf"
                                     .format(wo_root_domain))
            WOFileUtils.create_symlink(self, ["/etc/letsencrypt/shared/"
                                              "{0}.conf"
                                              .format(wo_root_domain),
                                              '/var/www/{0}/conf/nginx/'
                                              'ssl.conf'
                                              .format(wo_domain_name)])
        except IOError as e:
            Log.debug(self, str(e))
            Log.debug(self, "Error occured while "
                      "creating symlink for ssl cert")

# letsencrypt cert renewal


def renewLetsEncrypt(self, wo_domain_name):

    ssl = WOShellExec.cmd_exec(
        self, "/etc/letsencrypt/acme.sh "
              "--config-home "
              "'/etc/letsencrypt/config' "
              "--renew -d {0} --ecc --force"
        .format(wo_domain_name))

    # mail_list = ''
    if not ssl:
        Log.error(self, "ERROR : Let's Encrypt certificate renewal FAILED!",
                  False)
        if (SSL.getExpirationDays(self, wo_domain_name) > 0):
            Log.error(self, "Your current certificate will expire within " +
                      str(SSL.getExpirationDays(self, wo_domain_name)) +
                      " days.", False)
        else:
            Log.error(self, "Your current certificate already expired!", False)

        # WOSendMail("wordops@{0}".format(wo_domain_name), wo_wp_email,
        #  "[FAIL] HTTPS cert renewal {0}".format(wo_domain_name),
        #          "Hi,\n\nHTTPS certificate renewal for https://{0}
        # was unsuccessful.".format(wo_domain_name) +
        #           "\nPlease check the WordOps log for reason
        # The current expiry date is : " +
        #           str(SSL.getExpirationDate(self, wo_domain_name)) +
        #           "\n\nFor support visit https://wordops.net/support .
        # \n\nBest regards,\nYour WordOps Worker", files=mail_list,
        #           port=25, isTls=False)
        Log.error(self, "Check the WO log for more details "
                  "`tail /var/log/wo/wordops.log`")

    WOGit.add(self, ["/etc/letsencrypt"],
              msg="Adding letsencrypt folder")
    # WOSendMail("wordops@{0}".format(wo_domain_name), wo_wp_email,
    # "[SUCCESS] Let's Encrypt certificate renewal {0}".format(wo_domain_name),
    #           "Hi,\n\nYour Let's Encrypt certificate has been renewed for
    # https://{0} .".format(wo_domain_name) +
    #           "\nYour new certificate will expire on : " +
    #          str(SSL.getExpirationDate(self, wo_domain_name)) +
    #           "\n\nBest regards,\nYour WordOps Worker", files=mail_list,
    #           port=25, isTls=False)

# redirect= False to disable https redirection


def setupHsts(self, wo_domain_name):
    Log.info(
        self, "Adding /var/www/{0}/conf/nginx/hsts.conf"
        .format(wo_domain_name))

    hstsconf = open("/var/www/{0}/conf/nginx/hsts.conf"
                    .format(wo_domain_name),
                    encoding='utf-8', mode='w')
    hstsconf.write("more_set_headers "
                   "\"Strict-Transport-Security: "
                   "max-age=31536000; "
                   "includeSubDomains; "
                   "preload\";")
    hstsconf.close()
    return 0


def httpsRedirect(self, wo_domain_name, redirect=True, wildcard=False):
    if redirect:
        if os.path.isfile("/etc/nginx/conf.d/force-ssl-{0}.conf.disabled"
                          .format(wo_domain_name)):
            WOFileUtils.mvfile(self,
                               "/etc/nginx/conf.d/force-ssl-{0}.conf.disabled"
                               .format(wo_domain_name),
                               "/etc/nginx/conf.d/force-ssl-{0}.conf"
                               .format(wo_domain_name))
        else:
            if wildcard:
                try:
                    sslconf = open("/etc/nginx/conf.d/force-ssl-{0}.conf"
                                   .format(wo_domain_name),
                                   encoding='utf-8', mode='w')
                    sslconf.write("server {\n"
                                  "\tlisten 80;\n" +
                                  "\tlisten [::]:80;\n" +
                                  "\tserver_name *.{0} {0};\n"
                                  .format(wo_domain_name) +
                                  "\treturn 301 https://$host"
                                  "$request_uri;\n}")
                    sslconf.close()
                except IOError as e:
                    Log.debug(self, str(e))
                    Log.debug(self, "Error occured while generating "
                              "/etc/nginx/conf.d/force-ssl-{0}.conf"
                              .format(wo_domain_name))

            else:
                try:
                    sslconf = open("/etc/nginx/conf.d/force-ssl-{0}.conf"
                                   .format(wo_domain_name),
                                   encoding='utf-8', mode='w')
                    sslconf.write("server {\n"
                                  "\tlisten 80;\n" +
                                  "\tlisten [::]:80;\n" +
                                  "\tserver_name www.{0} {0};\n"
                                  .format(wo_domain_name) +
                                  "\treturn 301 https://{0}"
                                  .format(wo_domain_name)+"$request_uri;\n}")
                    sslconf.close()

                except IOError as e:
                    Log.debug(self, str(e))
                    Log.debug(self, "Error occured while generating "
                              "/etc/nginx/conf.d/force-ssl-{0}.conf"
                              .format(wo_domain_name))

        Log.info(self, "Added HTTPS Force Redirection for Site "
                 " http://{0}".format(wo_domain_name))
        # Nginx Configation into GIT
        WOGit.add(self,
                  ["/etc/nginx"], msg="Adding /etc/nginx/conf.d/"
                  "force-ssl-{0}.conf".format(wo_domain_name))
    else:
        if os.path.isfile("/etc/nginx/conf.d/force-ssl-{0}.conf"
                          .format(wo_domain_name)):
            WOFileUtils.mvfile(self, "/etc/nginx/conf.d/force-ssl-{0}.conf"
                               .format(wo_domain_name),
                               "/etc/nginx/conf.d/force-ssl-{0}.conf.disabled"
                               .format(wo_domain_name))
            Log.info(self, "Disabled HTTPS Force Redirection for Site "
                     " http://{0}".format(wo_domain_name))


def archivedCertificateHandle(self, domain):
    Log.warn(self, "You already have an existing certificate "
                   "for the domain requested.\n"
             "(ref: {0}/"
             "{1}_ecc/{1}.conf)".format(WOVariables.wo_ssl_archive, domain) +
             "\nPlease select an option from below?"
             "\n\t1: Reinstall existing certificate"
             "\n\t2: Renew & replace the certificate (limit ~5 per 7 days)"
             "")
    check_prompt = input(
        "\nType the appropriate number [1-2] or any other key to cancel: ")
    if not os.path.isfile("{0}/{1}/fullchain.pem"
                          .format(WOVariables.wo_ssl_live, domain)):
        Log.error(
            self, "{0}/{1}/fullchain.pem file is missing."
                  .format(WOVariables.wo_ssl_live, domain))

    if check_prompt == "1":
        Log.info(self, "Reinstalling SSL cert with acme.sh")
        ssl = WOShellExec.cmd_exec(self, "mkdir -p {0}/{1} && "
                                   "/etc/letsencrypt/acme.sh "
                                   "--config-home "
                                   "'/etc/letsencrypt/config' "
                                   "--install-cert -d {1} --ecc "
                                   "--cert-file {0}/{1}/cert.pem "
                                   "--key-file {0}/{1}/key.pem "
                                   "--fullchain-file "
                                   "{0}/{1}/fullchain.pem "
                                   "--ca-file {0}/{1}/ca.pem "
                                   "--reloadcmd "
                                   "\"nginx -t && service nginx restart\" "
                                   .format(WOVariables.wo_ssl_live,
                                           domain))
        if ssl:

            try:

                if not os.path.isfile("/var/www/{0}/conf/nginx/ssl.conf"
                                      .format(domain)):
                    Log.info(
                        self, "Adding /var/www/{0}/conf/nginx/ssl.conf"
                        .format(domain))

                    sslconf = open("/var/www/{0}/conf/nginx/ssl.conf"
                                   .format(domain),
                                   encoding='utf-8', mode='w')
                    sslconf.write("listen 443 ssl http2;\n"
                                  "listen [::]:443 ssl http2;\n"
                                  "ssl_certificate     "
                                  "{0}/{1}/fullchain.pem;\n"
                                  "ssl_certificate_key     {0}/{1}/key.pem;\n"
                                  "ssl_trusted_certificate {0}/{1}/ca.pem;\n"
                                  "ssl_stapling_verify on;\n"
                                  .format(WOVariables.wo_ssl_live, domain))
                    sslconf.close()

            except IOError as e:
                Log.debug(self, str(e))
                Log.debug(self, "Error occured while generating "
                          "ssl.conf")

    elif (check_prompt == "2"):
        Log.info(self, "Issuing SSL cert with acme.sh")
        ssl = WOShellExec.cmd_exec(self, "/etc/letsencrypt/acme.sh "
                                   "--config-home "
                                   "'/etc/letsencrypt/config' "
                                   "--renew -d {0} --ecc "
                                   "--force"
                                   .format(domain))

        if ssl:

            try:

                WOShellExec.cmd_exec(self, "mkdir -p {0}/{1} && "
                                     "/etc/letsencrypt/acme.sh "
                                     "--config-home "
                                     "'/etc/letsencrypt/config' "
                                     "--install-cert -d {1} --ecc "
                                     "--cert-file {0}/{1}/cert.pem "
                                     "--key-file {0}/{1}/key.pem "
                                     "--fullchain-file "
                                     "{0}/{1}/fullchain.pem "
                                     "ssl_trusted_certificate "
                                     "{0}/{1}/ca.pem;\n"
                                     "--reloadcmd "
                                     "\"nginx -t && service nginx restart\" "
                                     .format(WOVariables.wo_ssl_live, domain))

            except IOError as e:
                Log.debug(self, str(e))
                Log.debug(self, "Error occured while installing "
                          "the certificate")

    else:
        Log.error(self, "Operation cancelled by user.")

    if os.path.isfile("{0}/conf/nginx/ssl.conf"
                      .format(domain)):
        Log.info(self, "Existing ssl.conf . Backing it up ..")
        WOFileUtils.mvfile(self, "/var/www/{0}/conf/nginx/ssl.conf"
                           .format(domain),
                           '/var/www/{0}/conf/nginx/ssl.conf.bak'
                           .format(domain))

    return ssl
