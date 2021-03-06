###########################################################################
#          (C) Vrije Universiteit, Amsterdam (the Netherlands)            #
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

"""Class to deal with http browsing"""
import lxml.html
import requests
import time


class RedirectError(Exception):
    def __init__(self, status_code, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_code = status_code


class Session(requests.Session):
    """Provides a HTTP session, HTML parsing and a few convenience methods"""
    def __init__(self):
        super(Session, self).__init__()
        self.sleep = 0
        self.encoding = "utf-8"
        self.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0"
        })

    def get_html(self, link, **kwargs):
        content = self.get_content(link, **kwargs)
        result = lxml.html.fromstring(content, base_url=link)
        return result

    def get_content(self, link, **kwargs):
        response = self.get(link, **kwargs)
        response.raise_for_status()
        content = response.content  # type: bytes
        return content.decode(self.encoding)

    def get_redirected_url(self, link, **kwargs):
        response = self.get(link, allow_redirects=False, **kwargs)
        if response.status_code != 302:
            raise RedirectError(response.status_code, "Response did not return 302, but {} for {}.".format(response.status_code, link))
        #if response.status_code == 404:
         #   print(f"status_code={response.status_code}")
          #  return None
        return response.headers["Location"]

    def get(self, link, tries=3, **kwargs):
        time.sleep(self.sleep)

        try:
            return super(Session, self).get(link.strip(), **kwargs)
        except Exception:
            if tries == 1:
                raise
            time.sleep(2)
            return self.get(link, tries=tries - 1, **kwargs)

