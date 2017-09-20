# -*- coding: utf-8 -*-

# Copyright(C) 2012-2013 Florent Fourcot
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

from __future__ import print_function

from decimal import Decimal

from weboob.capabilities.bill import CapDocument, Detail, Subscription
from weboob.tools.application.repl import ReplApplication, defaultcount
from weboob.tools.application.formatters.iformatter import PrettyFormatter
from weboob.tools.application.base import MoreResultsAvailable
from weboob.core import CallErrors

__all__ = ['Boobill']


class SubscriptionsFormatter(PrettyFormatter):
    MANDATORY_FIELDS = ('id', 'label')

    def get_title(self, obj):
        if obj.renewdate:
            return u"%s - %s" % (obj.label, obj.renewdate.strftime('%d/%m/%y'))
        return obj.label


class Boobill(ReplApplication):
    APPNAME = 'boobill'
    VERSION = '1.4'
    COPYRIGHT = 'Copyright(C) 2012-YEAR Florent Fourcot'
    DESCRIPTION = 'Console application allowing to get/download documents and bills.'
    SHORT_DESCRIPTION = "get/download documents and bills"
    CAPS = CapDocument
    COLLECTION_OBJECTS = (Subscription, )
    EXTRA_FORMATTERS = {'subscriptions':   SubscriptionsFormatter,
                        }
    DEFAULT_FORMATTER = 'table'
    COMMANDS_FORMATTERS = {'subscriptions':   'subscriptions',
                           'ls':              'subscriptions',
                          }

    def main(self, argv):
        self.load_config()
        return ReplApplication.main(self, argv)

    def exec_method(self, id, method):
        l = []
        id, backend_name = self.parse_id(id)

        if not id:
            for subscrib in self.get_object_list('iter_subscription'):
                l.append((subscrib.id, subscrib.backend))
        else:
            l.append((id, backend_name))

        more_results = []
        not_implemented = []
        self.start_format()
        for id, backend in l:
            names = (backend,) if backend is not None else None
            try:
                for result in self.do(method, id, backends=names):
                    self.format(result)
            except CallErrors as errors:
                for backend, error, backtrace in errors:
                    if isinstance(error, MoreResultsAvailable):
                        more_results.append(id + u'@' + backend.name)
                    elif isinstance(error, NotImplementedError):
                        if backend not in not_implemented:
                            not_implemented.append(backend)
                    else:
                        self.bcall_error_handler(backend, error, backtrace)

        if len(more_results) > 0:
            print('Hint: There are more results available for %s (use option -n or count command)' % (', '.join(more_results)), file=self.stderr)
        for backend in not_implemented:
            print(u'Error(%s): This feature is not supported yet by this backend.' % backend.name, file=self.stderr)

    def do_subscriptions(self, line):
        """
        subscriptions

        List all subscriptions.
        """
        return self.do_ls(line)

    def do_details(self, id):
        """
        details [ID]

        Get details of subscriptions.
        If no ID given, display all details of all backends.
        """
        l = []
        id, backend_name = self.parse_id(id)

        if not id:
            for subscrib in self.get_object_list('iter_subscription'):
                l.append((subscrib.id, subscrib.backend))
        else:
            l.append((id, backend_name))

        for id, backend in l:
            names = (backend,) if backend is not None else None
            # XXX: should be generated by backend? -Flo
            # XXX: no, but you should do it in a specific formatter -romain
            # TODO: do it, and use exec_method here. Code is obsolete
            mysum = Detail()
            mysum.label = u"Sum"
            mysum.infos = u"Generated by boobill"
            mysum.price = Decimal("0.")

            self.start_format()
            for detail in self.do('get_details', id, backends=names):
                self.format(detail)
                mysum.price = detail.price + mysum.price

            self.format(mysum)

    def do_balance(self, id):
        """
        balance [ID]

        Get balance of subscriptions.
        If no ID given, display balance of all backends.
        """

        self.exec_method(id, 'get_balance')

    @defaultcount(10)
    def do_history(self, id):
        """
        history [ID]

        Get the history of subscriptions.
        If no ID given, display histories of all backends.
        """
        self.exec_method(id, 'iter_bills_history')

    @defaultcount(10)
    def do_documents(self, id):
        """
        documents [ID]

        Get the list of documents for subscriptions.
        If no ID given, display documents of all backends
        """
        self.exec_method(id, 'iter_documents')

    @defaultcount(10)
    def do_bills(self, id):
        """
        bills [ID]

        Get the list of bills documents for subscriptions.
        If no ID given, display bills of all backends
        """
        self.exec_method(id, 'iter_bills')

    def do_download(self, line, force_pdf=False):
        """
        download [ID | all] [FILENAME]

        download ID [FILENAME]

        download the document
        id is the identifier of the document (hint: try documents command)
        FILENAME is where to write the file. If FILENAME is '-',
        the file is written to stdout.

        download all [ID]

        You can use special word "all" and download all documents of
        subscription identified by ID.
        If Id not given, download documents of all subscriptions.
        """
        id, dest = self.parse_command_args(line, 2, 1)
        id, backend_name = self.parse_id(id)
        if not id:
            print('Error: please give a document ID (hint: use documents command)', file=self.stderr)
            return 2

        names = (backend_name,) if backend_name is not None else None

        # Special keywords, download all documents of all subscriptions
        if id == "all":
            callback = self.download_all if not force_pdf else self.download_all_pdf

            if dest is None:
                for subscription in self.do('iter_subscription', backends=names):
                    callback(subscription.id, names)
                return
            else:
                callback(dest, names)
                return

        if dest is None:
            for document in self.do('get_document', id, backends=names):
                dest = id + "." + (document.format if not force_pdf else 'pdf')

        if 'document' not in locals():
            document = id

        for buf in self.do('download_document' if not force_pdf else 'download_document_pdf', document, backends=names):
            if buf:
                if dest == "-":
                    print(buf)
                else:
                    try:
                        with open(dest, 'wb') as f:
                            f.write(buf)
                    except IOError as e:
                        print('Unable to write document in "%s": %s' % (dest, e), file=self.stderr)
                        return 1
                return

    def do_download_pdf(self, line):
        """
        download_pdf [id | all]

        download function with forced PDF conversion.
        """

        return self.do_download(line, force_pdf=True)

    def download_all(self, id, names, force_pdf=False):
        id, backend_name = self.parse_id(id)

        for document in self.do('iter_documents', id, backends=names):
            dest = document.id + "." + (document.format if not force_pdf else 'pdf')

            for buf in self.do('download_document' if not force_pdf else 'download_document_pdf', document, backends=names):
                if buf:
                    if dest == "-":
                        print(buf)
                    else:
                        try:
                            with open(dest, 'wb') as f:
                                f.write(buf)
                        except IOError as e:
                            print('Unable to write bill in "%s": %s' % (dest, e), file=self.stderr)
                            return 1
        return

    def download_all_pdf(self, id, names):
        """
        download_pdf all

        download_all function with forced PDF conversion.
        """

        return self.download_all(id, names, force_pdf=True)
