"""Debug Plugin for WordOps"""

from cement.core.controller import CementBaseController, expose
from cement.core import handler, hook
from wo.core.aptget import WOAptGet
from wo.core.shellexec import WOShellExec
from wo.core.mysql import WOMysql
from wo.core.services import WOService
from wo.core.logging import Log
from wo.cli.plugins.site_functions import logwatch
from wo.core.variables import WOVariables
from wo.core.fileutils import WOFileUtils
from pynginxconfig import NginxConfig
import os
import configparser
import glob
import signal


def wo_debug_hook(app):
    pass


class WODebugController(CementBaseController):
    class Meta:
        label = 'debug'
        description = 'Used for server level debugging'
        stacked_on = 'base'
        stacked_type = 'nested'
        arguments = [
            (['--stop'],
                dict(help='Stop debug', action='store_true')),
            (['--start'],
                dict(help='Start debug', action='store_true')),
            (['--import-slow-log'],
                dict(help='Import MySQL slow log to Anemometer database',
                     action='store_true')),
            (['--nginx'],
                dict(help='start/stop debugging nginx server '
                     'configuration for site',
                     action='store' or 'store_const',
                     choices=('on', 'off'), const='on', nargs='?')),
            (['--php'],
                dict(help='start/stop debugging server PHP 7.2 configuration',
                     action='store' or 'store_const',
                     choices=('on', 'off'), const='on', nargs='?')),
            (['--fpm'],
                dict(help='start/stop debugging fastcgi configuration',
                     action='store' or 'store_const',
                     choices=('on', 'off'), const='on', nargs='?')),
            (['--php73'],
                dict(help='start/stop debugging server PHP 7.3 configuration',
                     action='store' or 'store_const',
                     choices=('on', 'off'), const='on', nargs='?')),
            (['--fpm73'],
                dict(help='start/stop debugging fastcgi 7.3 configuration',
                     action='store' or 'store_const',
                     choices=('on', 'off'), const='on', nargs='?')),
            (['--mysql'],
                dict(help='start/stop debugging MySQL server',
                     action='store' or 'store_const',
                     choices=('on', 'off'), const='on', nargs='?')),
            (['--wp'],
                dict(help='start/stop wordpress debugging for site',
                     action='store' or 'store_const', choices=('on', 'off'),
                     const='on', nargs='?')),
            (['--rewrite'],
                dict(help='start/stop debugging nginx rewrite rules for site',
                     action='store' or 'store_const', choices=('on', 'off'),
                     const='on', nargs='?')),
            (['--all'],
                dict(help='start/stop debugging all server parameters',
                     action='store' or 'store_const', choices=('on', 'off'),
                     const='on', nargs='?')),
            (['-i', '--interactive'],
                dict(help='Interactive debug', action='store_true')),
            (['--import-slow-log-interval'],
                dict(help='Import MySQL slow log to Anemometer',
                     action='store', dest='interval')),
            (['site_name'],
                dict(help='Website Name', nargs='?', default=None))
        ]
        usage = "wo debug [<site_name>] [options] "

    @expose(hide=True)
    def debug_nginx(self):
        """Start/Stop Nginx debug"""
        # start global debug
        if (self.app.pargs.nginx == 'on' and not self.app.pargs.site_name):
            try:
                debug_address = (self.app.config.get('stack', 'ip-address')
                                 .split())
            except Exception as e:
                Log.debug(self, "{0}".format(e))
                debug_address = ['0.0.0.0/0']

            # Check if IP address is 127.0.0.1 then enable debug globally
            if debug_address == ['127.0.0.1'] or debug_address == []:
                debug_address = ['0.0.0.0/0']

            for ip_addr in debug_address:
                if not ("debug_connection "+ip_addr in open('/etc/nginx/'
                                                            'nginx.conf',
                                                            encoding='utf-8').read()):
                    Log.info(self, "Setting up Nginx debug connection"
                             " for "+ip_addr)
                    WOShellExec.cmd_exec(self, "sed -i \"/events {{/a\\ \\ \\ "
                                               "\\ $(echo debug_connection "
                                               "{ip}\;)\" /etc/nginx/"
                                               "nginx.conf".format(ip=ip_addr))
                    self.trigger_nginx = True

            if not self.trigger_nginx:
                Log.info(self, "Nginx debug connection already enabled")

            self.msg = self.msg + ["/var/log/nginx/*.error.log"]

        # stop global debug
        elif (self.app.pargs.nginx == 'off' and not self.app.pargs.site_name):
            if "debug_connection " in open('/etc/nginx/nginx.conf',
                                           encoding='utf-8').read():
                Log.info(self, "Disabling Nginx debug connections")
                WOShellExec.cmd_exec(self, "sed -i \"/debug_connection.*/d\""
                                     " /etc/nginx/nginx.conf")
                self.trigger_nginx = True
            else:
                Log.info(self, "Nginx debug connection already disabled")

        # start site specific debug
        elif (self.app.pargs.nginx == 'on' and self.app.pargs.site_name):
            config_path = ("/etc/nginx/sites-available/{0}"
                           .format(self.app.pargs.site_name))
            if os.path.isfile(config_path):
                if not WOShellExec.cmd_exec(self, "grep \"error.log debug\" "
                                            "{0}".format(config_path)):
                    Log.info(self, "Starting NGINX debug connection for "
                             "{0}".format(self.app.pargs.site_name))
                    WOShellExec.cmd_exec(self, "sed -i \"s/error.log;/"
                                         "error.log "
                                         "debug;/\" {0}".format(config_path))
                    self.trigger_nginx = True

                else:
                    Log.info(self, "Nginx debug for site already enabled")

                self.msg = self.msg + ['{0}{1}/logs/error.log'
                                       .format(WOVariables.wo_webroot,
                                               self.app.pargs.site_name)]

            else:
                Log.info(self, "{0} domain not valid"
                         .format(self.app.pargs.site_name))

        # stop site specific debug
        elif (self.app.pargs.nginx == 'off' and self.app.pargs.site_name):
            config_path = ("/etc/nginx/sites-available/{0}"
                           .format(self.app.pargs.site_name))
            if os.path.isfile(config_path):
                if WOShellExec.cmd_exec(self, "grep \"error.log debug\" {0}"
                                        .format(config_path)):
                    Log.info(self, "Stoping NGINX debug connection for {0}"
                             .format(self.app.pargs.site_name))
                    WOShellExec.cmd_exec(self, "sed -i \"s/error.log debug;/"
                                         "error.log;/\" {0}"
                                         .format(config_path))
                    self.trigger_nginx = True

                else:

                    Log.info(self, "Nginx debug for site already disabled")
            else:
                Log.info(self, "{0} domain not valid"
                         .format(self.app.pargs.site_name))

    @expose(hide=True)
    def debug_php(self):
        """Start/Stop PHP debug"""
        # PHP global debug start

        if (self.app.pargs.php == 'on' and not self.app.pargs.site_name):
            if not (WOShellExec.cmd_exec(self, "sed -n \"/upstream php"
                                               "{/,/}/p \" /etc/nginx/"
                                               "conf.d/upstream.conf "
                                               "| grep 9001")):

                Log.info(self, "Enabling PHP debug")

                # Change upstream.conf
                nc = NginxConfig()
                nc.loadf('/etc/nginx/conf.d/upstream.conf')
                nc.set([('upstream', 'php',), 'server'], '127.0.0.1:9001')
                nc.savef('/etc/nginx/conf.d/upstream.conf')

                # Enable xdebug
                WOFileUtils.searchreplace(self, "/etc/{0}/"
                                          "mods-available/".format("php/7.2") +
                                          "xdebug.ini",
                                          ";zend_extension",
                                          "zend_extension")

                # Fix slow log is not enabled default in PHP5.6
                config = configparser.ConfigParser()
                config.read('/etc/{0}/fpm/pool.d/debug.conf'.format("php/7.2"))
                config['debug']['slowlog'] = '/var/log/{0}/slow.log'.format(
                    "php/7.2")
                config['debug']['request_slowlog_timeout'] = '10s'
                with open('/etc/{0}/fpm/pool.d/debug.conf'.format("php/7.2"),
                          encoding='utf-8', mode='w') as confifile:
                    Log.debug(self, "Writting debug.conf configuration into "
                              "/etc/{0}/fpm/pool.d/debug.conf".format("php/7.2"))
                    config.write(confifile)

                self.trigger_php = True
                self.trigger_nginx = True
            else:
                Log.info(self, "PHP debug is already enabled")

            self.msg = self.msg + ['/var/log/{0}/slow.log'.format("php/7.2")]

        # PHP global debug stop
        elif (self.app.pargs.php == 'off' and not self.app.pargs.site_name):
            if WOShellExec.cmd_exec(self, " sed -n \"/upstream php {/,/}/p\" "
                                          "/etc/nginx/conf.d/upstream.conf "
                                          "| grep 9001"):
                Log.info(self, "Disabling PHP debug")

                # Change upstream.conf
                nc = NginxConfig()
                nc.loadf('/etc/nginx/conf.d/upstream.conf')
                nc.set([('upstream', 'php',), 'server'], '127.0.0.1:9000')
                nc.savef('/etc/nginx/conf.d/upstream.conf')

                # Disable xdebug
                WOFileUtils.searchreplace(self, "/etc/{0}/"
                                          "mods-available/".format("php/7.2") +
                                          "xdebug.ini",
                                          "zend_extension",
                                          ";zend_extension")

                self.trigger_php = True
                self.trigger_nginx = True
            else:
                Log.info(self, "PHP debug is already disabled")

    @expose(hide=True)
    def debug_fpm(self):
        """Start/Stop PHP5-FPM debug"""
        # PHP5-FPM start global debug
        if (self.app.pargs.fpm == 'on' and not self.app.pargs.site_name):
            if not WOShellExec.cmd_exec(self, "grep \"log_level = debug\" "
                                              "/etc/{0}/"
                                              "fpm/php-fpm.conf".format("php/7.2")):
                Log.info(self, "Setting up PHP5-FPM log_level = debug")
                config = configparser.ConfigParser()
                config.read('/etc/{0}/fpm/php-fpm.conf'.format("php/7.2"))
                config.remove_option('global', 'include')
                config['global']['log_level'] = 'debug'
                config['global']['include'] = '/etc/{0}/fpm/pool.d/*.conf'.format(
                    "php/7.2")
                with open('/etc/{0}/fpm/php-fpm.conf'.format("php/7.2"),
                          encoding='utf-8', mode='w') as configfile:
                    Log.debug(self, "Writting php5-FPM configuration into "
                              "/etc/{0}/fpm/php-fpm.conf".format("php/7.2"))
                    config.write(configfile)
                self.trigger_php = True
            else:
                Log.info(self, "PHP5-FPM log_level = debug already setup")

            self.msg = self.msg + ['/var/log/{0}/fpm.log'.format("php/7.2")]

        # PHP5-FPM stop global debug
        elif (self.app.pargs.fpm == 'off' and not self.app.pargs.site_name):
            if WOShellExec.cmd_exec(self, "grep \"log_level = debug\" "
                                          "/etc/{0}/fpm/php-fpm.conf".format("php/7.2")):
                Log.info(self, "Disabling PHP5-FPM log_level = debug")
                config = configparser.ConfigParser()
                config.read('/etc/{0}/fpm/php-fpm.conf'.format("php/7.2"))
                config.remove_option('global', 'include')
                config['global']['log_level'] = 'notice'
                config['global']['include'] = '/etc/{0}/fpm/pool.d/*.conf'.format(
                    "php/7.2")
                with open('/etc/{0}/fpm/php-fpm.conf'.format("php/7.2"),
                          encoding='utf-8', mode='w') as configfile:
                    Log.debug(self, "writting php5 configuration into "
                              "/etc/{0}/fpm/php-fpm.conf".format("php/7.2"))
                    config.write(configfile)

                self.trigger_php = True
            else:
                Log.info(self, "PHP5-FPM log_level = debug  already disabled")

    @expose(hide=True)
    def debug_php73(self):
        """Start/Stop PHP debug"""
        # PHP global debug start

        if (self.app.pargs.php73 == 'on' and not self.app.pargs.site_name):
            if not (WOShellExec.cmd_exec(self, "sed -n \"/upstream php73"
                                               "{/,/}/p \" /etc/nginx/"
                                               "conf.d/upstream.conf "
                                               "| grep 9173")):

                Log.info(self, "Enabling PHP 7.3 debug")

                # Change upstream.conf
                nc = NginxConfig()
                nc.loadf('/etc/nginx/conf.d/upstream.conf')
                nc.set([('upstream', 'php73',), 'server'], '127.0.0.1:9173')
                nc.savef('/etc/nginx/conf.d/upstream.conf')

                # Enable xdebug
                WOFileUtils.searchreplace(self, "/etc/php/7.3/mods-available/"
                                          "xdebug.ini",
                                          ";zend_extension",
                                          "zend_extension")

                # Fix slow log is not enabled default in PHP5.6
                config = configparser.ConfigParser()
                config.read('/etc/php/7.3/fpm/pool.d/debug.conf')
                config['debug']['slowlog'] = '/var/log/php/7.3/slow.log'
                config['debug']['request_slowlog_timeout'] = '10s'
                with open('/etc/php/7.3/fpm/pool.d/debug.conf',
                          encoding='utf-8', mode='w') as confifile:
                    Log.debug(self, "Writting debug.conf configuration into "
                              "/etc/php/7.3/fpm/pool.d/debug.conf")
                    config.write(confifile)

                self.trigger_php = True
                self.trigger_nginx = True
            else:
                Log.info(self, "PHP debug is already enabled")

            self.msg = self.msg + ['/var/log/php/7.3/slow.log']

        # PHP global debug stop
        elif (self.app.pargs.php73 == 'off' and not self.app.pargs.site_name):
            if WOShellExec.cmd_exec(self, " sed -n \"/upstream "
                                    "php72 {/,/}/p\" "
                                          "/etc/nginx/conf.d/upstream.conf "
                                          "| grep 9172"):
                Log.info(self, "Disabling PHP 7.2 debug")

                # Change upstream.conf
                nc = NginxConfig()
                nc.loadf('/etc/nginx/conf.d/upstream.conf')
                nc.set([('upstream', 'php72',), 'server'],
                       'unix:/var/run/php/php72-fpm.sock')
                nc.savef('/etc/nginx/conf.d/upstream.conf')

                # Disable xdebug
                WOFileUtils.searchreplace(self, "/etc/php/7.2/mods-available/"
                                          "xdebug.ini",
                                          "zend_extension",
                                          ";zend_extension")

                self.trigger_php = True
                self.trigger_nginx = True
            else:
                Log.info(self, "PHP 7.2 debug is already disabled")

    @expose(hide=True)
    def debug_fpm73(self):
        """Start/Stop PHP5-FPM debug"""
        # PHP5-FPM start global debug
        if (self.app.pargs.fpm73 == 'on' and not self.app.pargs.site_name):
            if not WOShellExec.cmd_exec(self, "grep \"log_level = debug\" "
                                              "/etc/php/7.3/fpm/php-fpm.conf"):
                Log.info(self, "Setting up PHP7.3-FPM log_level = debug")
                config = configparser.ConfigParser()
                config.read('/etc/php/7.3/fpm/php-fpm.conf')
                config.remove_option('global', 'include')
                config['global']['log_level'] = 'debug'
                config['global']['include'] = '/etc/php/7.3/fpm/pool.d/*.conf'
                with open('/etc/php/7.3/fpm/php-fpm.conf',
                          encoding='utf-8', mode='w') as configfile:
                    Log.debug(self, "Writing the PHP configuration into "
                              "/etc/php/7.3/fpm/php-fpm.conf")
                    config.write(configfile)
                self.trigger_php = True
            else:
                Log.info(self, "PHP7.3-FPM log_level = debug already setup")

            self.msg = self.msg + ['/var/log/php/7.3/fpm.log']

        # PHP5-FPM stop global debug
        elif (self.app.pargs.fpm73 == 'off' and not self.app.pargs.site_name):
            if WOShellExec.cmd_exec(self, "grep \"log_level = debug\" "
                                          "/etc/php/7.3/fpm/php-fpm.conf"):
                Log.info(self, "Disabling PHP7.3-FPM log_level = debug")
                config = configparser.ConfigParser()
                config.read('/etc/php/7.3/fpm/php-fpm.conf')
                config.remove_option('global', 'include')
                config['global']['log_level'] = 'notice'
                config['global']['include'] = '/etc/php/7.3/fpm/pool.d/*.conf'
                with open('/etc/php/7.3/fpm/php-fpm.conf',
                          encoding='utf-8', mode='w') as configfile:
                    Log.debug(self, "Writing the php7.3 configuration into "
                              "/etc/php/7.3/fpm/php-fpm.conf")
                    config.write(configfile)
                self.trigger_php = True
            else:
                Log.info(self, "PHP7.3-FPM log_level "
                         "= debug  already disabled")

    @expose(hide=True)
    def debug_mysql(self):
        """Start/Stop MySQL debug"""
        # MySQL start global debug
        if (self.app.pargs.mysql == 'on' and not self.app.pargs.site_name):
            if not WOShellExec.cmd_exec(self, "mysql -e \"show variables like"
                                              " \'slow_query_log\';\" | "
                                              "grep ON"):
                Log.info(self, "Setting up MySQL slow log")
                WOMysql.execute(self, "set global slow_query_log = "
                                      "\'ON\';")
                WOMysql.execute(self, "set global slow_query_log_file = "
                                      "\'/var/log/mysql/mysql-slow.log\';")
                WOMysql.execute(self, "set global long_query_time = 2;")
                WOMysql.execute(self, "set global log_queries_not_using"
                                      "_indexes = \'ON\';")
            else:
                Log.info(self, "MySQL slow log is already enabled")

            self.msg = self.msg + ['/var/log/mysql/mysql-slow.log']

        # MySQL stop global debug
        elif (self.app.pargs.mysql == 'off' and not self.app.pargs.site_name):
            if WOShellExec.cmd_exec(self, "mysql -e \"show variables like \'"
                                    "slow_query_log\';\" | grep ON"):
                Log.info(self, "Disabling MySQL slow log")
                WOMysql.execute(self, "set global slow_query_log = \'OFF\';")
                WOMysql.execute(self, "set global slow_query_log_file = \'"
                                "/var/log/mysql/mysql-slow.log\';")
                WOMysql.execute(self, "set global long_query_time = 10;")
                WOMysql.execute(self, "set global log_queries_not_using_index"
                                "es = \'OFF\';")
                WOShellExec.cmd_exec(self, "crontab -l | sed \'/#WordOps "
                                     "start/,/#WordOps end/d\' | crontab -")
            else:
                Log.info(self, "MySQL slow log already disabled")

    @expose(hide=True)
    def debug_wp(self):
        """Start/Stop WordPress debug"""
        if (self.app.pargs.wp == 'on' and self.app.pargs.site_name):
            wp_config = ("{0}/{1}/wp-config.php"
                         .format(WOVariables.wo_webroot,
                                 self.app.pargs.site_name))
            webroot = "{0}{1}".format(WOVariables.wo_webroot,
                                      self.app.pargs.site_name)
            # Check wp-config.php file into htdocs folder
            if not os.path.isfile(wp_config):
                wp_config = ("{0}/{1}/htdocs/wp-config.php"
                             .format(WOVariables.wo_webroot,
                                     self.app.pargs.site_name))
            if os.path.isfile(wp_config):
                if not WOShellExec.cmd_exec(self, "grep \"\'WP_DEBUG\'\" {0} |"
                                            " grep true".format(wp_config)):
                    Log.info(self, "Starting WordPress debug")
                    open("{0}/htdocs/wp-content/debug.log".format(webroot),
                         encoding='utf-8', mode='a').close()
                    WOShellExec.cmd_exec(self, "chown {1}: {0}/htdocs/wp-"
                                         "content/debug.log"
                                         "".format(webroot,
                                                   WOVariables.wo_php_user))
                    WOShellExec.cmd_exec(self, "sed -i \"s/define(\'WP_DEBUG\'"
                                         ".*/define(\'WP_DEBUG\', true);\\n"
                                         "define(\'WP_DEBUG_DISPLAY\', false);"
                                         "\\ndefine(\'WP_DEBUG_LOG\', true);"
                                         "\\ndefine(\'SAVEQUERIES\', true);/\""
                                         " {0}".format(wp_config))
                    WOShellExec.cmd_exec(self, "cd {0}/htdocs/ && wp"
                                         " plugin --allow-root install "
                                         "developer query-monitor"
                                         .format(webroot))
                    WOShellExec.cmd_exec(self, "chown -R {1}: {0}/htdocs/"
                                         "wp-content/plugins"
                                         .format(webroot,
                                                 WOVariables.wo_php_user))

                self.msg = self.msg + ['{0}{1}/htdocs/wp-content'
                                       '/debug.log'
                                       .format(WOVariables.wo_webroot,
                                               self.app.pargs.site_name)]

            else:
                Log.info(self, "Unable to find wp-config.php for site: {0}"
                         .format(self.app.pargs.site_name))

        elif (self.app.pargs.wp == 'off' and self.app.pargs.site_name):
            wp_config = ("{0}{1}/wp-config.php"
                         .format(WOVariables.wo_webroot,
                                 self.app.pargs.site_name))
            webroot = "{0}{1}".format(WOVariables.wo_webroot,
                                      self.app.pargs.site_name)
            # Check wp-config.php file into htdocs folder
            if not os.path.isfile(wp_config):
                wp_config = ("{0}/{1}/htdocs/wp-config.php"
                             .format(WOVariables.wo_webroot,
                                     self.app.pargs.site_name))
            if os.path.isfile(wp_config):
                if WOShellExec.cmd_exec(self, "grep \"\'WP_DEBUG\'\" {0} | "
                                        "grep true".format(wp_config)):
                    Log.info(self, "Disabling WordPress debug")
                    WOShellExec.cmd_exec(self, "sed -i \"s/define(\'WP_DEBUG\'"
                                         ", true);/define(\'WP_DEBUG\', "
                                         "false);/\" {0}".format(wp_config))
                    WOShellExec.cmd_exec(self, "sed -i \"/define(\'"
                                         "WP_DEBUG_DISPLAY\', false);/d\" {0}"
                                         .format(wp_config))
                    WOShellExec.cmd_exec(self, "sed -i \"/define(\'"
                                         "WP_DEBUG_LOG\', true);/d\" {0}"
                                         .format(wp_config))
                    WOShellExec.cmd_exec(self, "sed -i \"/define(\'"
                                         "SAVEQUERIES\', "
                                         "true);/d\" {0}".format(wp_config))
                else:
                    Log.info(self, "WordPress debug all already disabled")
        else:
            Log.error(self, "Missing argument site name")

    @expose(hide=True)
    def debug_rewrite(self):
        """Start/Stop Nginx rewrite rules debug"""
        # Start Nginx rewrite debug globally
        if (self.app.pargs.rewrite == 'on' and not self.app.pargs.site_name):
            if not WOShellExec.cmd_exec(self, "grep \"rewrite_log on;\" "
                                        "/etc/nginx/nginx.conf"):
                Log.info(self, "Setting up Nginx rewrite logs")
                WOShellExec.cmd_exec(self, "sed -i \'/http {/a \\\\t"
                                     "rewrite_log on;\' /etc/nginx/nginx.conf")
                self.trigger_nginx = True
            else:
                Log.info(self, "Nginx rewrite logs already enabled")

            if '/var/log/nginx/*.error.log' not in self.msg:
                self.msg = self.msg + ['/var/log/nginx/*.error.log']

        # Stop Nginx rewrite debug globally
        elif (self.app.pargs.rewrite == 'off' and
              not self.app.pargs.site_name):
            if WOShellExec.cmd_exec(self, "grep \"rewrite_log on;\" "
                                    "/etc/nginx/nginx.conf"):
                Log.info(self, "Disabling Nginx rewrite logs")
                WOShellExec.cmd_exec(self, "sed -i \"/rewrite_log.*/d\""
                                     " /etc/nginx/nginx.conf")
                self.trigger_nginx = True
            else:
                Log.info(self, "Nginx rewrite logs already disabled")
        # Start Nginx rewrite for site
        elif (self.app.pargs.rewrite == 'on' and self.app.pargs.site_name):
            config_path = ("/etc/nginx/sites-available/{0}"
                           .format(self.app.pargs.site_name))
            if not WOShellExec.cmd_exec(self, "grep \"rewrite_log on;\" {0}"
                                        .format(config_path)):
                Log.info(self, "Setting up Nginx rewrite logs for {0}"
                         .format(self.app.pargs.site_name))
                WOShellExec.cmd_exec(self, "sed -i \"/access_log/i \\\\\\t"
                                     "rewrite_log on;\" {0}"
                                     .format(config_path))
                self.trigger_nginx = True
            else:
                Log.info(self, "Nginx rewrite logs for {0} already setup"
                         .format(self.app.pargs.site_name))

            if ('{0}{1}/logs/error.log'.format(WOVariables.wo_webroot,
                                               self.app.pargs.site_name)
                    not in self.msg):
                self.msg = self.msg + ['{0}{1}/logs/error.log'
                                       .format(WOVariables.wo_webroot,
                                               self.app.pargs.site_name)]

        # Stop Nginx rewrite for site
        elif (self.app.pargs.rewrite == 'off' and self.app.pargs.site_name):
            config_path = ("/etc/nginx/sites-available/{0}"
                           .format(self.app.pargs.site_name))
            if WOShellExec.cmd_exec(self, "grep \"rewrite_log on;\" {0}"
                                    .format(config_path)):
                Log.info(self, "Disabling Nginx rewrite logs for {0}"
                         .format(self.app.pargs.site_name))
                WOShellExec.cmd_exec(self, "sed -i \"/rewrite_log.*/d\" {0}"
                                     .format(config_path))
                self.trigger_nginx = True
            else:
                Log.info(self, "Nginx rewrite logs for {0} already "
                         " disabled".format(self.app.pargs.site_name))

    @expose(hide=True)
    def signal_handler(self, signal, frame):
        """Handle Ctrl+c hevent for -i option of debug"""
        self.start = False
        if self.app.pargs.nginx:
            self.app.pargs.nginx = 'off'
            self.debug_nginx()
        if self.app.pargs.php:
            self.app.pargs.php = 'off'
            self.debug_php()
        if self.app.pargs.php73:
            self.app.pargs.php73 = 'off'
            self.debug_php73()
        if self.app.pargs.fpm:
            self.app.pargs.fpm = 'off'
            self.debug_fpm()
        if self.app.pargs.fpm73:
            self.app.pargs.fpm73 = 'off'
            self.debug_fpm73()
        if self.app.pargs.mysql:
            # MySQL debug will not work for remote MySQL
            if WOVariables.wo_mysql_host is "localhost":
                self.app.pargs.mysql = 'off'
                self.debug_mysql()
            else:
                Log.warn(self, "Remote MySQL found, WordOps does not support "
                         "debugging remote servers")
        if self.app.pargs.wp:
            self.app.pargs.wp = 'off'
            self.debug_wp()
        if self.app.pargs.rewrite:
            self.app.pargs.rewrite = 'off'
            self.debug_rewrite()

        # Reload Nginx
        if self.trigger_nginx:
            WOService.reload_service(self, 'nginx')

        # Reload PHP
        if self.trigger_php:
            if WOAptGet.is_installed(self, 'php7.2-fpm'):
                WOService.reload_service(self, 'php7.2-fpm')
            if WOAptGet.is_installed(self, 'php7.3-fpm'):
                WOService.reload_service(self, 'php7.3-fpm')
        self.app.close(0)

    @expose(hide=True)
    def default(self):
        """Default function of debug"""
        # self.start = True
        self.interactive = False
        self.msg = []
        self.trigger_nginx = False
        self.trigger_php = False

        if ((not self.app.pargs.nginx) and (not self.app.pargs.php) and
            (not self.app.pargs.php73) and (not self.app.pargs.fpm) and
            (not self.app.pargs.fpm73) and (not self.app.pargs.mysql) and
            (not self.app.pargs.wp) and (not self.app.pargs.rewrite) and
            (not self.app.pargs.all) and (not self.app.pargs.site_name) and
            (not self.app.pargs.import_slow_log) and
                (not self.app.pargs.interval)):
            if self.app.pargs.stop or self.app.pargs.start:
                print("--start/stop option is deprecated since wo v3.0.5")
                self.app.args.print_help()
            else:
                self.app.args.print_help()

        if self.app.pargs.import_slow_log:
            self.import_slow_log()

        if self.app.pargs.interval:
            try:
                cron_time = int(self.app.pargs.interval)
            except Exception as e:
                Log.debug(self, "{0}".format(e))
                cron_time = 5

            try:
                if not WOShellExec.cmd_exec(self, "crontab -l | grep "
                                            "'wo debug --import-slow-log'"):
                    if not cron_time == 0:
                        Log.info(self, "setting up crontab entry,"
                                 " please wait...")
                        WOShellExec.cmd_exec(self, "/bin/bash -c \"crontab -l "
                                             "2> /dev/null | {{ cat; echo -e"
                                             " \\\"#WordOps start MySQL "
                                             "slow log \\n*/{0} * * * * "
                                             "/usr/local/bin/wo debug"
                                             " --import-slow-log\\n"
                                             "#WordOps end MySQL slow log"
                                             "\\\"; }} | crontab -\""
                                             .format(cron_time))
                else:
                    if not cron_time == 0:
                        Log.info(self, "updating crontab entry,"
                                 " please wait...")
                        if not WOShellExec.cmd_exec(self, "/bin/bash -c "
                                                    "\"crontab "
                                                    "-l | sed '/WordOps "
                                                    "start MySQL slow "
                                                    "log/!b;n;c\*\/{0} "
                                                    "\* \* \* "
                                                    "\* \/usr"
                                                    "\/local\/bin\/wo debug "
                                                    "--import\-slow\-log' "
                                                    "| crontab -\""
                                                    .format(cron_time)):
                            Log.error(self, "failed to update crontab entry")
                    else:
                        Log.info(self, "removing crontab entry,"
                                 " please wait...")
                        if not WOShellExec.cmd_exec(self, "/bin/bash -c "
                                                    "\"crontab "
                                                    "-l | sed '/WordOps "
                                                    "start MySQL slow "
                                                    "log/,+2d'"
                                                    "| crontab -\""
                                                    .format(cron_time)):
                            Log.error(self, "failed to remove crontab entry")
            except CommandExecutionError as e:
                Log.debug(self, str(e))

        if self.app.pargs.all == 'on':
            if self.app.pargs.site_name:
                self.app.pargs.wp = 'on'
            self.app.pargs.nginx = 'on'
            self.app.pargs.php = 'on'
            self.app.pargs.fpm = 'on'
            if WOAptGet.is_installed(self, 'php7.2-fpm'):
                self.app.pargs.php73 = 'on'
                self.app.pargs.fpm73 = 'on'
            self.app.pargs.mysql = 'on'
            self.app.pargs.rewrite = 'on'

        if self.app.pargs.all == 'off':
            if self.app.pargs.site_name:
                self.app.pargs.wp = 'off'
            self.app.pargs.nginx = 'off'
            self.app.pargs.php = 'off'
            self.app.pargs.fpm = 'off'
            if WOAptGet.is_installed(self, 'php7.2-fpm'):
                self.app.pargs.php73 = 'off'
                self.app.pargs.fpm73 = 'off'
            self.app.pargs.mysql = 'off'
            self.app.pargs.rewrite = 'off'

        if ((not self.app.pargs.nginx) and (not self.app.pargs.php) and
                (not self.app.pargs.php73) and (not self.app.pargs.fpm) and
                (not self.app.pargs.fpm73) and (not self.app.pargs.mysql) and
                (not self.app.pargs.wp) and (not self.app.pargs.rewrite) and
                self.app.pargs.site_name):
            self.app.args.print_help()
            # self.app.pargs.nginx = 'on'
            # self.app.pargs.wp = 'on'
            # self.app.pargs.rewrite = 'on'

        if self.app.pargs.nginx:
            self.debug_nginx()
        if self.app.pargs.php:
            self.debug_php()
        if self.app.pargs.fpm:
            self.debug_fpm()
        if self.app.pargs.php73:
            self.debug_php73()
        if self.app.pargs.fpm73:
            self.debug_fpm73()
        if self.app.pargs.mysql:
            # MySQL debug will not work for remote MySQL
            if WOVariables.wo_mysql_host == "localhost":
                self.debug_mysql()
            else:
                Log.warn(self, "Remote MySQL found, WordOps does not support "
                         "debugging remote servers")
        if self.app.pargs.wp:
            self.debug_wp()
        if self.app.pargs.rewrite:
            self.debug_rewrite()

        if self.app.pargs.interactive:
            self.interactive = True

        # Reload Nginx
        if self.trigger_nginx:
            WOService.reload_service(self, 'nginx')
        # Reload PHP
        if self.trigger_php:
            if WOAptGet.is_installed(self, 'php7.2-fpm'):
                WOService.restart_service(self, 'php7.2-fpm')
            if WOAptGet.is_installed(self, 'php7.3-fpm'):
                WOService.restart_service(self, 'php7.3-fpm')

        if len(self.msg) > 0:
            if not self.app.pargs.interactive:
                disp_msg = ' '.join(self.msg)
                Log.info(self, "Use following command to check debug logs:\n" +
                         Log.ENDC + "tail -f {0}".format(disp_msg))
            else:
                signal.signal(signal.SIGINT, self.signal_handler)
                watch_list = []
                for w_list in self.msg:
                    watch_list = watch_list + glob.glob(w_list)

                logwatch(self, watch_list)

    @expose(hide=True)
    def import_slow_log(self):
        """Default function for import slow log"""
        if os.path.isdir("{0}22222/htdocs/db/anemometer"
                         .format(WOVariables.wo_webroot)):
            if os.path.isfile("/var/log/mysql/mysql-slow.log"):
                # Get Anemometer user name and password
                Log.info(self, "Importing MySQL slow log to Anemometer")
                host = os.popen("grep -e \"\'host\'\" {0}22222/htdocs/"
                                .format(WOVariables.wo_webroot) +
                                "db/anemometer/conf/config.inc.php  "
                                "| head -1 | cut -d\\\' -f4 | "
                                "tr -d '\n'").read()
                user = os.popen("grep -e \"\'user\'\" {0}22222/htdocs/"
                                .format(WOVariables.wo_webroot) +
                                "db/anemometer/conf/config.inc.php  "
                                "| head -1 | cut -d\\\' -f4 | "
                                "tr -d '\n'").read()
                password = os.popen("grep -e \"\'password\'\" {0}22222/"
                                    .format(WOVariables.wo_webroot) +
                                    "htdocs/db/anemometer/conf"
                                    "/config.inc.php "
                                    "| head -1 | cut -d\\\' -f4 | "
                                    "tr -d '\n'").read()

                # Import slow log Anemometer using pt-query-digest
                try:
                    WOShellExec.cmd_exec(self, "pt-query-digest --user={0} "
                                         "--password={1} "
                                         "--review D=slow_query_log,"
                                         "t=global_query_review "
                                         "--history D=slow_query_log,t="
                                         "global_query_review_history "
                                         "--no-report --limit=0% "
                                         "--filter=\" \\$event->{{Bytes}} = "
                                         "length(\\$event->{{arg}}) "
                                         "and \\$event->{{hostname}}=\\\""
                                         "{2}\\\"\" "
                                         "/var/log/mysql/mysql-slow.log"
                                         .format(user, password, host))
                except CommandExecutionError as e:
                    Log.debug(self, str(e))
                    Log.error(self, "MySQL slow log import failed.")
            else:
                Log.error(self, "MySQL slow log file not found,"
                          " so not imported slow logs")
        else:
            Log.error(self, "Anemometer is not installed." +
                      Log.ENDC + "\n Install Anemometer with:" +
                      Log.BOLD + "\n `wo stack install --utils`" +
                      Log.ENDC)


def load(app):
    # register the plugin class.. this only happens if the plugin is enabled
    handler.register(WODebugController)
    # register a hook (function) to run after arguments are parsed.
    hook.register('post_argument_parsing', wo_debug_hook)
