# -*- coding: utf-8 -*-

# Copyright(C) 2016       Baptiste Delpey
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

from __future__ import unicode_literals

from base64 import b64decode
import datetime
from decimal import Decimal
import re
from io import BytesIO
from datetime import date

from weboob.browser.pages import HTMLPage, LoggedPage, pagination, NextPage, FormNotFound, PartialHTMLPage, LoginPage, CsvPage
from weboob.browser.elements import ListElement, ItemElement, method, TableElement, SkipItem, DictElement
from weboob.browser.filters.standard import (
    CleanText, CleanDecimal, Field, Format,
    Regexp, Date, AsyncLoad, Async, Eval, RegexpError, Env,
    Currency as CleanCurrency,
)
from weboob.browser.filters.json import Dict
from weboob.browser.filters.html import Attr, Link, TableCell, AbsoluteLink
from weboob.capabilities.bank import Account, Investment, Recipient, Transfer, AccountNotFound, AddRecipientError, TransferInvalidAmount
from weboob.capabilities.base import NotAvailable, empty
from weboob.capabilities.profile import Person
from weboob.tools.capabilities.bank.transactions import FrenchTransaction
from weboob.tools.value import Value
from weboob.tools.date import parse_french_date
from weboob.tools.captcha.virtkeyboard import VirtKeyboard, VirtKeyboardError
from weboob.tools.compat import urljoin
from weboob.exceptions import BrowserQuestion, BrowserIncorrectPassword, BrowserHTTPNotFound, BrowserUnavailable, ActionNeeded


class BrowserAuthenticationCodeMaxLimit(BrowserIncorrectPassword):
    pass


class IncidentPage(HTMLPage):
    pass


class IbanPage(LoggedPage, HTMLPage):
    def get_iban(self):
        if self.doc.xpath('//div[has-class("alert")]/p[contains(text(), "Une erreur est survenue")]') or \
           self.doc.xpath('//div[has-class("alert")]/p[contains(text(), "Le compte est introuvable")]'):
            return NotAvailable
        return CleanText('//table[thead[tr[th[contains(text(), "Code I.B.A.N")]]]]/tbody/tr/td[2]', replace=[(' ', '')])(self.doc)


class AuthenticationPage(HTMLPage):
    def authenticate(self):
        self.logger.info('Using the PIN Code %s to login', self.browser.config['pin_code'].get())
        self.logger.info('Using the auth_token %s to login', self.browser.auth_token)

        form = self.get_form()
        form['otp_confirm[otpCode]'] = self.browser.config['pin_code'].get()
        form['flow_secureForm_instance'] = self.browser.auth_token
        form['otp_confirm[validate]'] = ''
        form['flow_secureForm_step'] = 2
        form.submit()

        self.browser.auth_token = None

    def sms_first_step(self):
        """
        This function simulates the registration of a device on
        boursorama two factor authentification web page.
        @param device device name to register
        @exception BrowserAuthenticationCodeMaxLimit when daily limit is consumed
        """
        form = self.get_form()
        form.submit()

    def sms_second_step(self):
        # <div class="form-errors"><ul><li>Vous avez atteint le nombre maximal de demandes pour aujourd&#039;hui</li></ul></div>
        error = CleanText('//div[has-class("form-errors")]')(self.doc)
        if len(error) > 0:
            raise BrowserIncorrectPassword(error)

        form = self.get_form()
        self.browser.auth_token = form['flow_secureForm_instance']
        form['otp_prepare[receiveCode]'] = ''
        form.submit()

        raise BrowserQuestion(Value('pin_code', label='Enter the PIN Code'))


class Transaction(FrenchTransaction):
    PATTERNS = [(re.compile('^(Virement .* )?VIR( SEPA)? (?P<text>.*)'), FrenchTransaction.TYPE_TRANSFER),
                (re.compile(u'^CHQ\. (?P<text>.*)'),        FrenchTransaction.TYPE_CHECK),
                (re.compile('^(ACHAT|PAIEMENT) CARTE (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{2}) (?P<text>.*)'),
                                                            FrenchTransaction.TYPE_CARD),
                (re.compile(r'^(?P<text>.+)?(ACHAT|PAIEMENT) CARTE (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{4}) (?P<text2>.*)'),
                                                            FrenchTransaction.TYPE_CARD),
                (re.compile(r'^(?P<text>.+)?((ACHAT|PAIEMENT)\s)?CARTE (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{4}) (?P<text2>.*)'),
                                                            FrenchTransaction.TYPE_DEFERRED_CARD),
                (re.compile('^(PRLV SEPA |PRLV |TIP )(?P<text>.*)'),
                                                            FrenchTransaction.TYPE_ORDER),
                (re.compile('^RETRAIT DAB (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{2}) (?P<text>.*)'),
                                                            FrenchTransaction.TYPE_WITHDRAWAL),
                (re.compile(r'^([A-Z][\sa-z]* )?RETRAIT DAB (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{4}) (?P<text>.*)'),
                                                            FrenchTransaction.TYPE_WITHDRAWAL),
                (re.compile('^AVOIR (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{2}) (?P<text>.*)'),   FrenchTransaction.TYPE_PAYBACK),
                (re.compile(r'^(?P<text>[A-Z][\sa-z]* )?AVOIR (?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{4}) (?P<text2>.*)'),   FrenchTransaction.TYPE_PAYBACK),
                (re.compile('^REM CHQ (?P<text>.*)'), FrenchTransaction.TYPE_DEPOSIT),
                (re.compile(u'^([*]{3} solde des operations cb [*]{3} )?Relevé différé Carte (.*)'), FrenchTransaction.TYPE_CARD_SUMMARY),
               ]


class VirtKeyboardPage(HTMLPage):
    pass


class BoursoramaVirtKeyboard(VirtKeyboard):
    symbols = {'0': (17, 7, 24, 17),
               '1': (18, 6, 21, 18),
               '2': (9, 7, 32, 34),
               '3': (10, 7, 31, 34),
               '4': (11, 6, 29, 34),
               '5': (14, 6, 28, 34),
               '6': (7, 7, 34, 34),
               '7': (5, 6, 36, 34),
               '8': (8, 7, 32, 34),
               '9': (4, 7, 38, 34)}

    color = (255,255,255)

    def __init__(self, page):
        self.md5 = {}
        for button in page.doc.xpath('//ul[@class="password-input"]//button'):
            c = button.attrib['data-matrix-key']
            txt = button.attrib['style'].replace('background-image:url(data:image/png;base64,', '').rstrip(');')
            img = BytesIO(b64decode(txt.encode('ascii')))
            self.load_image(img, self.color, convert='RGB')
            self.load_symbols((0, 0, 42, 42), c)

    def load_symbols(self, coords, c):
        coord = self.get_symbol_coords(coords)
        if coord == (-1, -1, -1, -1):
            return
        self.md5[coord] = c

    def get_code(self, password):
        code = ''
        for i, d in enumerate(password):
            if i > 0:
                code += '|'
            try:
                code += self.md5[self.symbols[d]]
            except KeyError:
                raise VirtKeyboardError()
        return code


class LoginPage(LoginPage, HTMLPage):
    TO_DIGIT = {'2': ['a', 'b', 'c'],
                '3': ['d', 'e', 'f'],
                '4': ['g', 'h', 'i'],
                '5': ['j', 'k', 'l'],
                '6': ['m', 'n', 'o'],
                '7': ['p', 'q', 'r', 's'],
                '8': ['t', 'u', 'v'],
                '9': ['w', 'x', 'y', 'z']
               }

    def login(self, login, password):
        if not password.isdigit():
            password = ''.join([c if c.isdigit() else [k for k, v in self.TO_DIGIT.items() if c in v][0] for c in password.lower()])
        form = self.get_form()
        keyboard_page = self.browser.keyboard.open()
        vk = BoursoramaVirtKeyboard(keyboard_page)
        code = vk.get_code(password)
        form['form[login]'] = login
        form['form[fakePassword]'] = len(password) * '•'
        form['form[password]'] = code
        form['form[matrixRandomChallenge]'] = re.search('val\("(.*)"', CleanText('//script')(keyboard_page.doc)).group(1)
        form.submit()


class StatusPage(LoggedPage, PartialHTMLPage):
    def on_load(self):
        # sometimes checking accounts are missing
        msg = CleanText('//div[has-class("alert--danger")]', default=None)(self.doc)
        if msg:
            raise BrowserUnavailable(msg)


class AccountsPage(LoggedPage, HTMLPage):
    def is_here(self):
        return not self.doc.xpath('//div[contains(@id, "alert-random")]')

    ACCOUNT_TYPES = {u'comptes courants':      Account.TYPE_CHECKING,
                     u'cav':                   Account.TYPE_CHECKING,
                     u'comptes épargne':       Account.TYPE_SAVINGS,
                     u'mon épargne':           Account.TYPE_SAVINGS,
                     'csljeune':               Account.TYPE_SAVINGS, # in url
                     u'ord':                   Account.TYPE_MARKET,
                     u'comptes bourse':        Account.TYPE_MARKET,
                     u'mes placements financiers': Account.TYPE_MARKET,
                     u'av':                    Account.TYPE_LIFE_INSURANCE,
                     u'assurances vie':        Account.TYPE_LIFE_INSURANCE,
                     u'assurance-vie':         Account.TYPE_LIFE_INSURANCE,
                     u'mes crédits':           Account.TYPE_LOAN,
                     u'crédit':                Account.TYPE_LOAN,
                     u'prêt':                  Account.TYPE_LOAN,
                     u'pea':                   Account.TYPE_PEA,
                     'carte':                  Account.TYPE_CARD,
                    }

    @method
    class iter_accounts(ListElement):
        item_xpath = '//table[@class="table table--accounts"]/tr[has-class("table__line--account") and count(descendant::td) > 1 and @data-line-account-href]'

        class item(ItemElement):
            klass = Account

            load_details = Field('url') & AsyncLoad

            def condition(self):
                return not self.is_external() and not 'automobile' in Field('url')(self)

            obj_label = CleanText('.//a[has-class("account--name")] | .//div[has-class("account--name")]')

            obj_currency = FrenchTransaction.Currency('.//a[has-class("account--balance")]')
            obj_valuation_diff = Async('details') & CleanDecimal('//li[h4[text()="Total des +/- values"]]/h3 |\
                        //li[span[text()="Total des +/- values latentes"]]/span[has-class("overview__value")]', replace_dots=True, default=NotAvailable)
            obj__holder = None

            obj__amount = CleanDecimal('.//a[has-class("account--balance")]', replace_dots=True)

            def obj_balance(self):
                if Field('type')(self) != Account.TYPE_CARD:
                    balance = Field('_amount')(self)
                    if Field('type')(self) in [Account.TYPE_PEA, Account.TYPE_LIFE_INSURANCE]:
                        page = Async('details').loaded_page(self)
                        if isinstance(page, MarketPage):
                            return page.get_balance(Field('type')(self)) or balance
                    return balance
                return Decimal('0')

            def obj_coming(self):
                # report deferred expenses in the coming attribute
                if Field('type')(self) == Account.TYPE_CARD:
                    return Field('_amount')(self)
                return Async('details', CleanDecimal(u'//li[h4[text()="Mouvements à venir"]]/h3', replace_dots=True, default=NotAvailable))(self)

            def obj_id(self):
                type = Field('type')(self)
                if type == Account.TYPE_CARD:
                    # When card is opposed it still appears on accounts page with a dead link and so, no id. Skip it.
                    if Attr('.//a[has-class("account--name")]', 'href')(self) == '#':
                        raise SkipItem()
                    return self.obj__idparts()[1]

                id = Async('details', Regexp(CleanText('//h3[has-class("account-number")]'), r'(\d+)', default=NotAvailable))(self)
                if not id:
                    raise SkipItem()
                return id

            def obj_type(self):
                # card url is /compte/cav/xxx/carte/yyy so reverse to match "carte" before "cav"
                for word in Field('url')(self).lower().split('/')[::-1]:
                    v = self.page.ACCOUNT_TYPES.get(word)
                    if v:
                        return v

                for word in Field('label')(self).replace('_', ' ').lower().split():
                    v = self.page.ACCOUNT_TYPES.get(word)
                    if v:
                        return v

                category = CleanText('./preceding-sibling::tr[has-class("list--accounts--master")]//h4')(self)
                v = self.page.ACCOUNT_TYPES.get(category.lower())
                if v:
                    return v

                page = Async('details').loaded_page(self)
                if isinstance(page, LoanPage):
                    return Account.TYPE_LOAN

                return Account.TYPE_UNKNOWN

            def obj_url(self):
                link = Attr('.//a[has-class("account--name")] | .//a[2]', 'href', default=NotAvailable)(self)
                return urljoin(self.page.url, link)

            def is_external(self):
                return '/budget/' in Field('url')(self)

            def obj__idparts(self):
                return re.findall('[a-z\d]{32}', Field('url')(self))

            def obj__webid(self):
                parts = self.obj__idparts()
                if parts:
                    return parts[0]

            # We do not yield other banks accounts for the moment.
            def validate(self, obj):
                return not Async('details', CleanText(u'//h4[contains(text(), "Établissement bancaire")]'))(self) and not \
                    Async('details', CleanText(u'//h4/div[contains(text(), "Établissement bancaire")]'))(self)

    def iter_card_ids(self):
        for tr in self.doc.xpath('//table[@class="table table--accounts"]/tr[has-class("table__line--account") and count(descendant::td) > 1 and @data-line-account-href]'):
            url = Attr('.//a[@class="account--name"] | .//a[2]', 'href', default='')(tr)
            m = re.search(r'/([a-z0-9]+)/carte/([a-z0-9]+)', url)
            if m:
                yield m.groups()


class CalendarPage(LoggedPage, HTMLPage):
    def on_load(self):
        self.browser.deferred_card_calendar = []
        for tr in self.doc.xpath('//div[h3[contains(text(), "CALENDRIER")]]//tr[contains(@class, "table__line")]'):
            self.browser.deferred_card_calendar.append((parse_french_date(CleanText('./td[2]')(tr)), parse_french_date(CleanText('./td[3]')(tr))))


class HistoryPage(LoggedPage, HTMLPage):
    @method
    class iter_history(ListElement):
        item_xpath = '//ul[has-class("list__movement")]/li[div and not(contains(@class, "summary")) \
                                                               and not(contains(@class, "graph")) \
                                                               and not (contains(@class, "separator"))]'

        class item(ItemElement):
            klass = Transaction

            obj_raw = Transaction.Raw(CleanText('.//div[has-class("list__movement__line--label__name")]'))
            obj_date = Date(Attr('.//time', 'datetime'))
            obj_amount = CleanDecimal('.//div[has-class("list__movement__line--amount")]', replace_dots=True)
            obj_category = CleanText('.//div[has-class("category")]')

            def obj_id(self):
                return Attr('.', 'data-id', default=NotAvailable)(self) or Attr('.', 'data-custom-id', default=NotAvailable)(self)

            def obj_type(self):
                if not Env('is_card', default=False)(self):
                    if Env('coming', default=False)(self) and Field('raw')(self).startswith('CARTE '):
                        return Transaction.TYPE_CARD_SUMMARY
                    # keep the value previously set by Transaction.Raw
                    return self.obj.type
                return Transaction.TYPE_DEFERRED_CARD

            def obj_rdate(self):
                if self.obj.rdate:
                    # Transaction.Raw may have already set it
                    return self.obj.rdate

                s = Regexp(Field('raw'), ' (\d{2}/\d{2}/\d{2}) | (?!NUM) (\d{6}) ', default=NotAvailable)(self)
                if not s:
                    return Field('date')(self)
                s = s.replace('/', '')
                # Sometimes the user enters an invalid date 16/17/19 for example
                return Date(dayfirst=True, default=NotAvailable).filter('%s-%s-%s' % (s[:2], s[2:4], s[4:]))

            def obj__is_coming(self):
                return Env('coming', default=False)(self) or len(self.xpath(u'.//span[@title="Mouvement à débit différé"]')) or self.obj_date() > date.today()

            def obj_date(self):
                date = Date(Attr('.//time', 'datetime'))(self)
                if Env('is_card', default=False)(self):
                    if self.page.browser.deferred_card_calendar is None:
                        self.page.browser.location(Link('//a[contains(text(), "calendrier")]')(self))
                    closest = self.page.browser.get_debit_date(date)
                    if closest:
                        return closest
                return date

            # These are on deffered cards accounts.
            def condition(self):
                return not len(self.xpath(u'.//span[has-class("icon-carte-bancaire")]')) and \
                       not len(self.xpath(u'.//a[contains(@href, "/carte")]'))

    def get_cards_number_link(self):
        return Link('//a[small[span[contains(text(), "carte bancaire")]]]', default=NotAvailable)(self.doc)

    def get_csv_link(self):
        return Link('//a[@data-operations-export-button]')(self.doc)

    def get_calendar_link(self):
        return Link('//a[contains(text(), "calendrier")]')(self.doc)


class CardHistoryPage(LoggedPage, CsvPage):
    ENCODING = 'latin-1'
    FMTPARAMS = {'delimiter': str(';')}
    HEADER = 1

    @method
    class iter_history(DictElement):
        class item(ItemElement):
            klass = Transaction

            obj_raw = Transaction.Raw(Dict('label'))
            obj_date = Date(Dict('dateVal'), dayfirst=True)
            obj__account_label = Dict('accountLabel')
            obj__is_coming = False

            def obj_amount(self):
                if Field('type')(self) == Transaction.TYPE_CARD_SUMMARY:
                    # '-' so the reimbursements appear positively in the card transactions:
                    return -CleanDecimal(Dict('amount'), replace_dots=True)(self)
                return CleanDecimal(Dict('amount'), replace_dots=True)(self)

            def obj_rdate(self):
                if self.obj.rdate:
                    # Transaction.Raw may have already set it
                    return self.obj.rdate

                s = Regexp(Field('raw'), ' (\d{2}/\d{2}/\d{2}) | (?!NUM) (\d{6}) ', default=NotAvailable)(self)
                if not s:
                    return Field('date')(self)
                s = s.replace('/', '')
                # Sometimes the user enters an invalid date 16/17/19 for example
                return Date(dayfirst=True, default=NotAvailable).filter('%s%s%s%s%s' % (s[:2], '-', s[2:4], '-', s[4:]))

            def obj_type(self):
                if 'CARTE' in self.obj.raw:
                    return Transaction.TYPE_DEFERRED_CARD
                return self.obj.type

            def obj_category(self):
                return Dict('category')(self)

            # The csv page shows every transactions of the card account AND the associated
            # check account. Here we want only the card transactions.
            # Also, if there is more than one card account, the csv page will show
            # transactions of every card account (smart) ... So we need to check for
            # account number.
            def validate(self, obj):
                if "Relevé" in obj.raw:
                    return Env('account_number')(self) in obj.raw
                return ("CARTE" in obj.raw or "CARTE" in obj._account_label) and Env('account_number')(self) in Dict('accountNum')(self)


class Myiter_investment(TableElement):
    item_xpath = '//table[contains(@class, "operations")]/tbody/tr'
    head_xpath = '//table[contains(@class, "operations")]/thead/tr/th'

    col_value = u'Valeur'
    col_quantity = u'Quantité'
    col_unitprice = u'Px. Revient'
    col_unitvalue = u'Cours'
    col_valuation = u'Montant'
    col_diff = u'+/- latentes'


class Myitem(ItemElement):
    klass = Investment

    obj_quantity = CleanDecimal(TableCell('quantity'), default=NotAvailable)
    obj_unitprice = CleanDecimal(TableCell('unitprice'), replace_dots=True, default=NotAvailable)
    obj_unitvalue = CleanDecimal(TableCell('unitvalue'), replace_dots=True, default=NotAvailable)
    obj_valuation = CleanDecimal(TableCell('valuation'), replace_dots=True, default=NotAvailable)
    obj_diff = CleanDecimal(TableCell('diff'), replace_dots=True, default=NotAvailable)

    def obj_label(self):
        return CleanText().filter((TableCell('value')(self)[0]).xpath('.//a'))

    def obj_code(self):
        return CleanText().filter((TableCell('value')(self)[0]).xpath('./span')) or NotAvailable


def my_pagination(func):
    def inner(page, *args, **kwargs):
        while True:
            try:
                for r in func(page, *args, **kwargs):
                    yield r
            except NextPage as e:
                try:
                    result = page.browser.location(e.request)
                    page = result.page
                except BrowserHTTPNotFound as e:
                    page.logger.warning(e)
                    return
            else:
                return
    return inner


class MarketPage(LoggedPage, HTMLPage):
    def get_balance(self, account_type):
        txt = u"Solde au" if account_type is Account.TYPE_LIFE_INSURANCE else u"Total Portefeuille"
        return CleanDecimal('//li[h4[contains(text(), "%s")]]/h3' % txt, replace_dots=True, default=None)(self.doc)

    @my_pagination
    @method
    class iter_history(TableElement):
        item_xpath = '//table/tbody/tr'
        head_xpath = '//table/thead/tr/th'

        col_label = ['Nature', u'Opération']
        col_amount = 'Montant'
        col_date = ["Date d'effet", 'Date', u'Date opération']

        next_page = Link('//li[@class="pagination__next"]/a')

        class item(ItemElement):
            klass = Transaction

            def obj_date(self):
                d = Date(CleanText(TableCell('date')), dayfirst=True, default=None)(self)
                if d:
                    return d
                return Date(CleanText(TableCell('date')), parse_func=parse_french_date)(self)

            obj_raw = Transaction.Raw(CleanText(TableCell('label')))
            obj_amount = CleanDecimal(TableCell('amount'), replace_dots=True, default=NotAvailable)
            obj__is_coming = False

            def parse(self, el):
                if el.xpath('./td[2]/a'):
                    m = re.search('(\d+)', el.xpath('./td[2]/a')[0].get('data-modal-alert-behavior', ''))
                    if m:
                        self.env['account']._history_pages.append((Field('raw')(self),\
                                                                self.page.browser.open('%s%s%s' % (self.page.url.split('mouvements')[0], 'mouvement/', m.group(1))).page))
                        raise SkipItem()

    @method
    class get_investment(Myiter_investment):
        class item (Myitem):
            def obj_unitvalue(self):
                return CleanDecimal(replace_dots=True, default=NotAvailable).filter((TableCell('unitvalue')(self)[0]).xpath('./span[not(@class)]'))

    def iter_investment(self):
        valuation = CleanDecimal('//li[h4[contains(text(), "Solde Espèces")]]/h3', replace_dots=True, default=None)(self.doc)
        if valuation:
            inv = Investment()
            inv.code = u"XX-liquidity"
            inv.label = u"Liquidités"
            inv.valuation = valuation
            yield inv

        for inv in self.get_investment():
            yield inv

    def get_transactions_from_detail(self, account):
        for label, page in account._history_pages:
            amounts = page.doc.xpath('//span[contains(text(), "Montant")]/following-sibling::span')
            if len(amounts) == 3:
                amounts.pop(0)
            for table in page.doc.xpath('//table'):
                t = Transaction()

                t.date = Date(CleanText(page.doc.xpath('//span[contains(text(), "Date d\'effet")]/following-sibling::span')), dayfirst=True)(page)
                t.label = label
                t.amount = CleanDecimal(replace_dots=True).filter(amounts[0])
                amounts.pop(0)
                t._is_coming = False
                t.investments = []
                sum_amount = 0
                for tr in table.xpath('./tbody/tr'):
                    i = Investment()
                    i.label = CleanText().filter(tr.xpath('./td[1]'))
                    i.vdate = Date(CleanText(tr.xpath('./td[2]')), dayfirst=True)(tr)
                    i.unitvalue = CleanDecimal(replace_dots=True).filter(tr.xpath('./td[3]'))
                    i.quantity = CleanDecimal(replace_dots=True).filter(tr.xpath('./td[4]'))
                    i.valuation = CleanDecimal(replace_dots=True).filter(tr.xpath('./td[5]'))
                    sum_amount += i.valuation
                    t.investments.append(i)

                if t.label == 'prélèvement':
                    t.amount = sum_amount

                yield t


class SavingMarketPage(MarketPage):
    @pagination
    @method
    class iter_history(TableElement):
        item_xpath = '//table/tbody/tr'
        head_xpath = '//table/thead/tr/th'

        col_label = u'Opération'
        col_amount = u'Montant'
        col_date = u'Date opération'
        col_vdate = u'Date Val'

        next_page = Link('//li[@class="pagination__next"]/a')

        class item(ItemElement):
            klass = Transaction

            obj_label = CleanText(TableCell('label'))
            obj_amount = CleanDecimal(TableCell('amount'), replace_dots=True)
            obj__is_coming = False

            def obj_date(self):
                return parse_french_date(CleanText(TableCell('date'))(self))

            def obj_vdate(self):
                return parse_french_date(CleanText(TableCell('vdate'))(self))

    @method
    class iter_investment(TableElement):
        item_xpath = '//table/tbody/tr[count(descendant::td) > 4]'
        head_xpath = '//table/thead/tr[count(descendant::th) > 4]/th'

        col_label = u'Fonds'
        col_code = u'Code Isin'
        col_unitvalue = u'Valeur de la part'
        col_quantity = u'Nombre de parts'
        col_vdate = u'Date VL'

        class item(ItemElement):
            klass = Investment

            obj_label = CleanText(TableCell('label'))
            obj_code = CleanText(TableCell('code'))
            obj_unitvalue = CleanDecimal(TableCell('unitvalue'), replace_dots=True)
            obj_quantity = CleanDecimal(TableCell('quantity'), replace_dots=True)
            obj_valuation = Eval(lambda x, y: x * y, Field('quantity'), Field('unitvalue'))
            obj_vdate = Date(CleanText(TableCell('vdate')), dayfirst=True)


class AsvPage(MarketPage):
    @method
    class iter_investment(Myiter_investment):
        col_vdate = u'Date de Valeur'
        col_label = u'Valeur'

        class item(Myitem):
            obj_vdate = Date(CleanText(TableCell('vdate')), dayfirst=True, default=NotAvailable)

            def obj_label(self):
                return CleanText('.//strong/a')(self) or CleanText('.//strong', children=False)(self)


class AccbisPage(LoggedPage, HTMLPage):
    @method
    class iter_unvalid_cards(ListElement):
        # the only purpose of this is to detect opposed cards
        # because cards have an 'OPPOSÉE' label on this page only, not on AccountsPage...

        item_xpath = '//ul[@id="nav-category__BANK"]/li'

        class item(ItemElement):
            klass = Account

            def condition(self):
                return "add-card" not in self.el.attrib['class']

            # need a falsy value to circumvent detection of duplicates
            # since obj_id() not implemented and all card IDs would
            # be equal the default value
            # (see method weboob.browser.elements.ListElement.store)
            obj_id = None

            obj_label = CleanText('.//span[has-class("nav-category__name")]')
            obj_url = AbsoluteLink('.//a', default=NotAvailable)
            obj__tooltip = CleanText(Attr('.', 'title'))

            def obj_type(self):
                # card url is /compte/cav/xxx/carte/yyy so reverse to match "carte" before "cav"
                for word in Field('url')(self).lower().split('/')[::-1]:
                    v = AccountsPage.ACCOUNT_TYPES.get(word)
                    if v:
                        return v

                for word in Field('label')(self).replace('_', ' ').lower().split():
                    v = AccountsPage.ACCOUNT_TYPES.get(word)
                    if v:
                        return v

            def validate(self, obj):
                # keep only NON-VALID account
                # a valid account:
                # - is related to a credit card
                # - the card must not be blocked
                # - the card has to be already activated
                if obj.type != Account.TYPE_CARD:
                    return False
                if obj.label.endswith(' OPPOSÉE'):
                    return True
                # not activated when tooltip hides the 4 digits
                return obj._tooltip.endswith('****')


    def populate(self, accounts):
        cards = []
        for account in accounts:
            for li in self.doc.xpath('//li[@class="nav-category"]'):
                title = CleanText().filter(li.xpath('./h3'))
                for a in li.xpath('./ul/li//a'):
                    label = CleanText().filter(a.xpath('.//span[@class="nav-category__name"]'))
                    balance_el = a.xpath('.//span[@class="nav-category__value"]')
                    balance = CleanDecimal(replace_dots=True, default=NotAvailable).filter(balance_el)
                    if 'CARTE' in label and not empty(balance):
                        acc = Account()
                        acc.balance = balance
                        acc.label = label
                        acc.currency = FrenchTransaction.Currency().filter(balance_el)
                        acc.url = urljoin(self.url, Link().filter(a.xpath('.')))
                        acc._history_page = acc.url
                        try:
                            acc.id = acc._webid = Regexp(pattern='carte/(.*)$').filter(Link().filter(a.xpath('.')))
                        except RegexpError:
                            # Those are external cards, ie: amex cards
                            continue
                        acc.type = Account.TYPE_CARD
                        if not acc in cards:
                            cards.append(acc)
                    elif account.label == label and account.balance == balance:
                        if not account.type:
                            account.type = AccountsPage.ACCOUNT_TYPES.get(title, Account.TYPE_UNKNOWN)
                        account._webid = Attr(None, 'data-account-label').filter(a.xpath('.//span[@class="nav-category__name"]'))
        if cards:
            self.browser.go_cards_number(cards[0].url)
            if self.browser.cards.is_here():
                self.browser.page.populate_cards_number(cards)
                accounts.extend(cards)


class LoanPage(LoggedPage, HTMLPage):
    pass


class ErrorPage(HTMLPage):
    def on_load(self):
        error = (Attr('//input[@required][@id="profile_lei_type_identifier"]', 'data-message', default=None)(self.doc) or
                 CleanText('//h2[@class="page-title"][contains(text(), "Actualisation")]', default=None)(self.doc))
        if error:
            raise ActionNeeded(error)


class ExpertPage(LoggedPage, HTMLPage):
    pass


def MyInput(*args, **kwargs):
    args = (u'//input[contains(@name, "%s")]' % args[0], 'value',)
    kwargs.update(default=NotAvailable)
    return Attr(*args, **kwargs)


def MySelect(*args, **kwargs):
    args = (u'//select[contains(@name, "%s")]/option[@selected]' % args[0],)
    kwargs.update(default=NotAvailable)
    return CleanText(*args, **kwargs)


class ProfilePage(LoggedPage, HTMLPage):
    @method
    class get_profile(ItemElement):
        klass = Person

        obj_name = Format('%s %s %s', MySelect('genderTitle'), MyInput('firstName'), MyInput('lastName'))
        obj_nationality = CleanText(u'//span[contains(text(), "Nationalité")]/span')
        obj_spouse_name = MyInput('spouseFirstName')
        obj_children = CleanDecimal(MyInput('dependentChildren'), default=NotAvailable)
        obj_family_situation = MySelect('maritalStatus')
        obj_matrimonial = MySelect('matrimonial')
        obj_housing_status = MySelect('housingSituation')
        obj_job = MyInput('occupation')
        obj_job_start_date = Date(MyInput('employeeSince'), default=NotAvailable)
        obj_company_name = MyInput('employer')
        obj_socioprofessional_category = MySelect('socioProfessionalCategory')


class CardsNumberPage(LoggedPage, HTMLPage):
    def populate_cards_number(self, cards):
        # Checking account ID used to match credit cards
        # Label useful when several cards on the same checking account
        labels_ids = [
            (
                CleanText('.', replace=[('DEBIT DIFFERE ', '')])(o),
                re.search(r'/limite/(\w+)/', o.attrib['href']).group(1)
            )
            for o in self.doc.xpath('//select//option')
        ]

        # remove cards whose number ends with **** (means it is not activated yet)
        labels_ids = [
            label_id for label_id in labels_ids
            if not label_id[0].endswith('****')
        ]

        for card in cards:
            match = [
                label for label, account_id in labels_ids
                if card.label in label and account_id in card.url
            ]
            assert len(match) <= 1, "only one card should be matched, or zero if the card is not yet activated"
            if len(match) == 1 :
                card_label = match[0]
                card.number = re.search('(\d{4}\*{8}(\d{4}|\*{4}))', card_label).group(1)


class HomePage(LoggedPage, HTMLPage):
    pass


class NoTransferPage(LoggedPage, HTMLPage):
    pass


class TransferAccounts(LoggedPage, HTMLPage):
    @method
    class iter_accounts(ListElement):
        item_xpath = '//a[has-class("next-step")][@data-value]'

        class item(ItemElement):
            klass = Account

            obj_id = CleanText('.//div[@class="transfer__account-number"]')
            obj__sender_id = Attr('.', 'data-value')

    def submit_account(self, id):
        for account in self.iter_accounts():
            if account.id == id:
                break
        else:
            raise AccountNotFound()

        form = self.get_form(name='DebitAccount')
        form['DebitAccount[debitAccountKey]'] = account._sender_id
        form.submit()


class TransferRecipients(LoggedPage, HTMLPage):
    @method
    class iter_recipients(ListElement):
        item_xpath = '//a[has-class("transfer__account-wrapper")]'

        class item(ItemElement):
            klass = Recipient

            obj_id = CleanText('.//div[@class="transfer__account-number"]')
            obj_bank_name = Regexp(CleanText('.//div[@class="transfer__account-name"]'), pattern=r'- ([^-]*)$', default=NotAvailable)

            def obj_label(self):
                label = Regexp(CleanText('.//div[@class="transfer__account-name"]'), pattern=r'^(.*?)(?: -[^-]*)?$')(self)
                return label.rstrip('-').rstrip()

            def obj_category(self):
                text = CleanText('./ancestor::div[has-class("deploy--item")]//a[has-class("deploy__title")]')(self)
                if 'Mes comptes Boursorama Banque' in text:
                    return 'Interne'
                elif 'Comptes externes' in text or 'Comptes de tiers' in text:
                    return 'Externe'

            def obj_iban(self):
                if Field('category')(self) == 'Externe':
                    return Field('id')(self)

            def obj_enabled_at(self):
                return datetime.datetime.now().replace(microsecond=0)

            obj__tempid = Attr('.', 'data-value')

    def submit_recipient(self, tempid):
        form = self.get_form(name='CreditAccount')
        form['CreditAccount[creditAccountKey]'] = tempid
        form.submit()


class TransferCharac(LoggedPage, HTMLPage):
    def get_option(self, select, text):
        for opt in select.xpath('option'):
            if opt.text_content() == text:
                return opt.attrib['value']

    def submit_info(self, amount, label, exec_date):
        form = self.get_form(name='Characteristics')

        assert amount > 0
        amount = str(amount.quantize(Decimal('0.00'))).replace('.', ',')
        form['Characteristics[amount]'] = amount
        form['Characteristics[label]'] = label

        if not exec_date:
            exec_date = datetime.date.today()
        if datetime.date.today() == exec_date:
            assert self.get_option(form.el.xpath('//select[@id="Characteristics_schedulingType"]')[0], 'Ponctuel') == '1'
            form['Characteristics[schedulingType]'] = '1'
        else:
            assert self.get_option(form.el.xpath('//select[@id="Characteristics_schedulingType"]')[0], 'Différé') == '2'
            form['Characteristics[schedulingType]'] = '2'
            form['Characteristics[scheduledDate][day]'] = exec_date.strftime('%d')
            form['Characteristics[scheduledDate][month]'] = exec_date.strftime('%m')
            form['Characteristics[scheduledDate][year]'] = exec_date.strftime('%Y')

        form['Characteristics[notice]'] = 'none'
        form.submit()


class TransferConfirm(LoggedPage, HTMLPage):
    def on_load(self):
        errors = CleanText('//li[contains(text(), "Le montant du virement est inférieur au minimum")]')(self.doc)
        if errors:
            raise TransferInvalidAmount(message=errors)

    @method
    class get_transfer(ItemElement):
        klass = Transfer

        obj_label = CleanText('//div[@id="transfer-label"]/span[@class="transfer__account-value"]')
        obj_amount = CleanDecimal('//div[@id="transfer-amount"]/span[@class="transfer__account-value"]', replace_dots=True)
        obj_currency = CleanCurrency('//div[@id="transfer-amount"]/span[@class="transfer__account-value"]')

        obj_account_label = CleanText('//span[@id="transfer-origin-account"]')
        obj_recipient_label = CleanText('//span[@id="transfer-destination-account"]')

        def obj_exec_date(self):
            type_ = CleanText('//div[@id="transfer-type"]/span[@class="transfer__account-value"]')(self)
            if type_ == 'Ponctuel':
                return datetime.date.today()
            elif type_ == 'Différé':
                return Date(CleanText('//div[@id="transfer-date"]/span[@class="transfer__account-value"]'), dayfirst=True)(self)

    def submit(self):
        form = self.get_form(name='Confirm')
        form.submit()


class TransferSent(LoggedPage, HTMLPage):
    pass


class AddRecipientPage(LoggedPage, HTMLPage):
    def on_load(self):
        super(AddRecipientPage, self).on_load()

        err = CleanText('//div[@class="form-errors"]', default=None)(self.doc)
        if err:
            raise AddRecipientError(message=err)

    def _is_form(self, **kwargs):
        try:
            self.get_form(**kwargs)
        except FormNotFound:
            return False
        return True

    def is_charac(self):
        return self._is_form(name='externalAccountsPrepareType')

    def submit_recipient(self, recipient):
        form = self.get_form(name='externalAccountsPrepareType')
        form['externalAccountsPrepareType[type]'] = 'tiers'
        form['externalAccountsPrepareType[label]'] = recipient.label
        # names are mandatory and are uneditable...
        form['externalAccountsPrepareType[beneficiaryLastname]'] = recipient.label
        form['externalAccountsPrepareType[beneficiaryFirstname]'] = recipient.label
        form['externalAccountsPrepareType[bank]'] = recipient.bank_name or 'Autre'
        form['externalAccountsPrepareType[iban]'] = recipient.iban
        form.submit()

    def is_send_sms(self):
        return self._is_form(name='otp_prepare')

    def send_sms(self):
        form = self.get_form(name='otp_prepare')
        form['otp_prepare[receiveCode]'] = ''
        form.submit()

    def is_confirm_sms(self):
        return self._is_form(name='otp_confirm')

    def confirm_sms(self, code):
        form = self.get_form(name='otp_confirm')
        form['otp_confirm[otpCode]'] = code
        form.submit()

    def is_confirm(self):
        return self._is_form(name='externalAccountsConfirmType')

    def confirm(self):
        self.get_form(name='externalAccountsConfirmType').submit()

    def get_recipient(self):
        div = self.doc.xpath('//div[@class="confirmation__text"]')[0]

        ret = Recipient()
        ret.label = CleanText('//p[b[contains(text(),"Libellé du compte :")]]/text()')(div)
        ret.iban = ret.id = CleanText('//p[b[contains(text(),"Iban :")]]/text()')(div)
        ret.bank_name = CleanText(u'//p[b[contains(text(),"Établissement bancaire :")]]/text()')(div)
        ret.currency = u'EUR'
        ret.category = u'Externe'
        ret.enabled_at = datetime.date.today()
        assert ret.label
        return ret

    def is_created(self):
        return CleanText('//p[contains(text(), "Le bénéficiaire a bien été ajouté.")]')(self.doc) != ""


class PEPPage(LoggedPage, HTMLPage):
    pass
