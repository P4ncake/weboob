# -*- coding: utf-8 -*-

# Copyright(C) 2014 Romain Bignon
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


class BrowserIncorrectPassword(Exception):
    pass


class BrowserForbidden(Exception):
    pass


class BrowserBanned(BrowserIncorrectPassword):
    pass


class BrowserUnavailable(Exception):
    pass


class BrowserQuestion(BrowserIncorrectPassword):
    """
    When raised by a browser,
    """
    def __init__(self, *fields):
        self.fields = fields


class CaptchaQuestion(Exception):
    """Site requires solving a CAPTCHA (base class)"""
    # could be improved to pass the name of the backendconfig key

    def __init__(self, type=None, **kwargs):
        super(CaptchaQuestion, self).__init__("The site requires solving a captcha")
        self.type = type
        for key, value in kwargs.items():
            setattr(self, key, value)


class ImageCaptchaQuestion(CaptchaQuestion):
    type = 'image_captcha'

    image_data = None

    def __init__(self, image_data):
        super(ImageCaptchaQuestion, self).__init__(self.type, image_data=image_data)


class NocaptchaQuestion(CaptchaQuestion):
    type = 'g_recaptcha'

    website_key = None
    website_url = None

    def __init__(self, website_key, website_url):
        super(NocaptchaQuestion, self).__init__(self.type, website_key=website_key, website_url=website_url)


class RecaptchaQuestion(CaptchaQuestion):
    type = 'g_recaptcha'

    website_key = None
    website_url = None

    def __init__(self, website_key, website_url):
        super(RecaptchaQuestion, self).__init__(self.type, website_key=website_key, website_url=website_url)


class BrowserHTTPNotFound(BrowserUnavailable):
    pass


class BrowserHTTPError(BrowserUnavailable):
    pass


class BrowserHTTPSDowngrade(BrowserUnavailable):
    pass


class BrowserSSLError(BrowserUnavailable):
    pass


class ParseError(Exception):
    pass


class FormFieldConversionWarning(UserWarning):
    """
    A value has been set to a form's field and has been implicitly converted.
    """


class NoAccountsException(Exception):
    pass


class ModuleInstallError(Exception):
    pass


class ModuleLoadError(Exception):
    def __init__(self, module_name, msg):
        super(ModuleLoadError, self).__init__(msg)
        self.module = module_name


class ActionNeeded(Exception):
    pass


class AuthMethodNotImplemented(ActionNeeded):
    pass


class BrowserPasswordExpired(ActionNeeded):
    pass
