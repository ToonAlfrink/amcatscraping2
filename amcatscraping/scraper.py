###########################################################################
# (C) Vrije Universiteit, Amsterdam (the Netherlands)            #
#                                                                         #
# This file is part of AmCAT - The Amsterdam Content Analysis Toolkit     #
#                                                                         #
# AmCAT is free software: you can redistribute it and/or modify it under  #
# the terms of the GNU Lesser General Public License as published by the  #
# Free Software Foundation, either version 3 of the License, or (at your  #
# option) any later version.                                              #
#                                                                         #
# AmCAT is distributed in the hope that it will be useful, but WITHOUT    #
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or   #
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public     #
# License for more details.                                               #
#                                                                         #
# You should have received a copy of the GNU Lesser General Public        #
# License along with AmCAT.  If not, see <http://www.gnu.org/licenses/>.  #
###########################################################################
from __future__ import print_function

from operator import itemgetter
import os
import sys
import logging
from datetime import timedelta
from collections import OrderedDict

import __main__
from .httpsession import Session
from .tools import todatetime, todate, get_arguments, read_date
from amcatclient import AmcatAPI

log = logging.getLogger(__name__)

ARGLIST = OrderedDict((
    ('project', {'type': int}),
    ('articleset', {'type': int}),
    (('api_host', 'api_user', 'api_password'), {}),
    ('--log_errors', {'action': 'store_const', 'const': True})
))


def getpath(cls):
    """Get class path even if it's __main__

    TODO: Fix.. it relies on PYTHONPATH, seriously? :-/"""
    if cls.__module__ == "__main__":
        pythonpath = os.environ.get('PYTHONPATH', '')
        filepath = sys.path[0].split(pythonpath, 1)[1].strip("/")
        modulepath = ".".join(filepath.split("/"))
        filename = os.path.splitext(os.path.basename(__main__.__file__))[0]
        return modulepath + "." + filename
    else:
        return cls.__module__


class Scraper(object):
    def __init__(self, **kwargs):
        self.options = kwargs or get_arguments(ARGLIST)
        self.session = Session()  #http session
        self.project_id = self.options["project"]
        self.articleset_id = self.options["articleset"]

    def run(self, input=None):
        log.info("Scraping articles...")
        articles = []
        for a in self._scrape():
            articles.append(a)
            print(".", end="")
            sys.stdout.flush()
        print("")

        log.info("Found {} articles. Postprocessing...".format(len(articles)))
        articles = list(self._postprocess(articles))

        if self.options.get("command") == "test":
            log.info("Scraper returned %s articles", len(articles))
            return articles

        log.info("Saving..")
        return self._save(
            articles,
            self.options['api_host'],
            self.options['api_user'],
            self.options['api_password']
        )

    def _scrape(self):
        """Scrape the target resource and return a sequence of article dicts"""
        raise NotImplementedError()

    def _postprocess(self, articles):
        """Space to do something with the unsaved articles that the scraper provided"""
        for a in articles:
            if a:
                a['insertscript'] = getpath(self.__class__) + "." + self.__class__.__name__
                yield a

    def _save(self, articles, *auth):
        api = AmcatAPI(*auth)
        response = api.create_articles(self.project_id, self.articleset_id, json_data=articles)
        ids = [article['id'] for article in response]
        if not any(ids) and ids:
            raise RuntimeError("None of the articles were saved.")
        if not all(ids):
            warning_msg = "Warning: Only {}/{} articles were saved."
            log.warning(warning_msg.format(len(filter(None, ids)), len(ids)))
        return filter(itemgetter("id"), response)


class UnitScraper(Scraper):
    """
    Scrapes the resource on a per-unit basis
    children classes should overrride _get_units and _scrape_unit
    """

    def _scrape(self):
        for unit in self._get_units():
            try:
                yield self._scrape_unit(unit)
            except Exception as e:
                if self.options['log_errors']:
                    log.exception(e)
                else:
                    sys.stdout.write('x')
                    sys.stdout.flush()
                continue


class DateRangeScraper(Scraper):
    """
    Omits any articles that haven't been published in a given period.
    Provides a first_date and last_date option which children classes can use
    to select data from their resource.
    """

    def _get_arg_list(self):
        args = super(DateRangeScraper, self)._get_arg_list()
        args.append((('min_datetime', 'max_datetime'),
                     {'type': lambda x: todatetime(read_date(x))}))
        return args

    def __init__(self, **kwargs):
        super(DateRangeScraper, self).__init__(**kwargs)
        n_days = (self.options['max_datetime'] - self.options['min_datetime']).days
        self.dates = map(todate,
                         [self.options['min_datetime'] + timedelta(days=x) for x in
                          range(n_days + 1)])
        self.mindatetime = self.options['min_datetime']
        self.maxdatetime = self.options['max_datetime']

    def _postprocess(self, articles):
        articles = list(super(DateRangeScraper, self)._postprocess(articles))
        for a in articles:
            _date = todatetime(a['date'])
            assert self.mindatetime <= _date <= self.maxdatetime
        return articles


class LoginError(Exception):
    """Exception for login failure"""
    pass


class LoginMixin(object):
    """Logs in to the resource before scraping"""

    def _get_arg_list(self):
        args = super(LoginMixin, self)._get_arg_list()
        args.append((('username', 'password'), {}))
        return args

    def _scrape(self, *args, **kwargs):
        username = self.options['username']
        password = self.options['password']
        # Please ensure _login returns True on success
        assert self._login(username, password)
        return super(LoginMixin, self)._scrape(*args, **kwargs)

    def _login(self, username, password):
        raise NotImplementedError()


class PropertyCheckMixin(object):
    """
    Before saving, this mixin has the scraper check whether all given article props are present
    and fill in the blanks with default values
    When mixing this in, make sure the scraper contains a '_props' member with the following structure:
    {
        'defaults' : {
            '<property1>' : '<value>',
            '<property2>' : '<value>',
            ...
            '<propertyN>' : '<value>'
            },
        'required' : ['<property1>', '<property2>', ..., '<propertyN>'],
        'expected' : ['<property1>', '<property2>', ..., '<propertyN>']
        }
    'required' means all articles should have this property
    'expected' means at least one article should have this property
    """

    def _postprocess(self, articles):
        articles = super(PropertyCheckMixin, self)._postprocess(articles)
        articles = self._add_defaults(articles)
        self._check_properties(articles)
        return articles

    def _add_defaults(self, articles):
        log.info("Filling in defaults...")
        self._props['defaults']['project'] = self.options['project']
        self._props['defaults']['metastring'] = {}
        for prop, default in self._props['defaults'].items():
            for article in articles:
                if not article.get(prop):
                    article[prop] = default
        return articles

    def _check_properties(self, articles):
        log.info("Checking properties...")
        for prop in self._props['required']:
            if not all(
                    [article.get(prop) or article['metastring'].get(prop) for article in articles]):
                raise ValueError("{prop} missing in at least one article".format(**locals()))
        if articles:
            for prop in self._props['expected']:
                if not any([article.get(prop) or article['metastring'].get(prop) for article in
                            articles]):
                    raise ValueError("{prop} missing in all articles".format(**locals()))