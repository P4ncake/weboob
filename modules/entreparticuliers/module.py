# -*- coding: utf-8 -*-

# Copyright(C) 2015      Bezleputh
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


from weboob.tools.backend import Module
from weboob.capabilities.housing import (CapHousing, HousingPhoto,
                                         ADVERT_TYPES)

from .browser import EntreparticuliersBrowser


__all__ = ['EntreparticuliersModule']


class EntreparticuliersModule(Module, CapHousing):
    NAME = 'entreparticuliers'
    DESCRIPTION = u'entreparticuliers.com website'
    MAINTAINER = u'Bezleputh'
    EMAIL = 'carton_ben@yahoo.fr'
    LICENSE = 'AGPLv3+'
    VERSION = '1.4'

    BROWSER = EntreparticuliersBrowser

    def search_city(self, pattern):
        return self.browser.search_city(pattern)

    def search_housings(self, query):
        if(len(query.advert_types) == 1 and
           query.advert_types[0] == ADVERT_TYPES.PROFESSIONAL):
            # Entreparticuliers is personal only
            return list()

        cities = [c for c in query.cities if c.backend == self.name]
        if len(cities) == 0:
            return []

        return self.browser.search_housings(query, cities)

    def get_housing(self, _id):
        return self.browser.get_housing(_id)

    def fill_photo(self, photo, fields):
        if 'data' in fields and photo.url and not photo.data:
            photo.data = self.browser.open(photo.url).content
        return photo

    OBJECTS = {HousingPhoto: fill_photo}
