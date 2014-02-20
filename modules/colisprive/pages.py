# -*- coding: utf-8 -*-

# Copyright(C) 2014 Florent Fourcot
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

from datetime import date
from weboob.tools.browser import BasePage
from weboob.capabilities.parcel import Parcel, Event


__all__ = ['TrackPage']


class TrackPage(BasePage):
    def get_info(self, _id):
        p = Parcel(_id)

        statustr = self.document.xpath('//tr[@class="bandeauText"]')[0]
        status = self.parser.tocleanstring(statustr.xpath('td')[1])

        p.info = status

        p.history = []
        for i, tr in enumerate(self.document.xpath('//div[@class="mainbloc4Evt"]//tr')):
            tds = tr.findall('td')
            try:
                if tds[0].attrib['class'] != "titrestatutdate2":
                    continue
            except:
                continue

            ev = Event(i)
            ev.location = None
            ev.activity = self.parser.tocleanstring(tds[1])
            ev.date = date(*reversed([int(x) for x in self.parser.tocleanstring(tds[0]).split('/')]))
            p.history.append(ev)

        return p
