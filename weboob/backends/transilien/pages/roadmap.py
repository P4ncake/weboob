# -*- coding: utf-8 -*-

# Copyright(C) 2010-2011 Romain Bignon
#
# This file is part of weboob.
#
# weboob is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# weboob is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with weboob. If not, see <http://www.gnu.org/licenses/>.


import re
import datetime

from weboob.tools.browser import BasePage
from weboob.tools.misc import to_unicode


__all__ = ['RoadmapPage']


class RoadmapSearchPage(BasePage):
    def search(self, departure, arrival):
        self.browser.select_form('formHiRecherche')
        self.browser['lieuDepart'] = departure.encode('utf-8')
        self.browser['lieuArrivee'] = arrival.encode('utf-8')
        self.browser.submit()

class RoadmapConfirmPage(BasePage):
    def select(self, name, num):
        try:
            self.browser[name] = str(num)
        except TypeError:
            self.browser[name] = [str(num)]

    def confirm(self):
        self.browser.select_form('form1')
        self.browser.set_all_readonly(False)
        self.select('idDepart', 1)
        self.select('idArrivee', 1)
        self.browser.submit()

class RoadmapPage(BasePage):
    def get_steps(self):
        current_step = None
        for tr in self.parser.select(self.document.getroot(), 'table.horaires2 tbody tr'):
            if not 'class' in tr.attrib:
                continue
            elif tr.attrib['class'] == 'trHautTroncon':
                current_step = {}
                current_step['id'] = 0
                current_step['start_time'] = self.parse_time(self.parser.select(tr, 'td.formattedHeureDepart p', 1).text.strip())
                current_step['line'] = self.parser.select(tr, 'td.rechercheResultatColumnMode img')[-1].attrib['alt']
                current_step['departure'] = to_unicode(self.parser.select(tr, 'td.descDepart p strong', 1).text.strip())
                current_step['duration'] = self.parse_duration(self.parser.select(tr, 'td.rechercheResultatVertAlign', 1).text.strip())
            elif tr.attrib['class'] == 'trBasTroncon':
                current_step['end_time'] = self.parse_time(self.parser.select(tr, 'td.formattedHeureArrivee p', 1).text.strip())
                current_step['arrival'] = to_unicode(self.parser.select(tr, 'td.descArrivee p strong', 1).text.strip())
                yield current_step

    def parse_time(self, time):
        h, m = time.split('h')
        return datetime.time(int(h), int(m))

    def parse_duration(self, dur):
        m = re.match('(\d+)min.', dur)
        if m:
            return datetime.timedelta(minutes=int(m.group(1)))
        m = re.match('(\d+)h(\d+)', dur)
        if m:
            return datetime.timedelta(hours=int(m.group(1)),
                                      minutes=int(m.group(2)))
