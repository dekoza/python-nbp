# -*- coding: utf-8 -*-
import os
import urllib2
from datetime import datetime, date, timedelta
from xml.dom import minidom

from . import dateutils, caching
from .models import Currency, Table


A = 'a'
B = 'b'
TABLE_TYPES = [A, B]


# URLS BUILDING AND GENERATION ##############################################
NBP_CURRENCY_TABLE_URL_PREFIX = 'http://rss.nbp.pl/kursy/xml2/'
NBP_CURRENCY_TABLE_URL_PATTERN = '%s/%s/%s%s%s.xml'
# order: year, table_type, short_year, table_type, pub_number

def build_url(year, pub_number, table_type, cache_dir=None):
    """
    Builds NBP currency table URL and cache_file_path if ``cache_dir``
    is provided.

    :param year:       year from you want to download currency rate
    :param pub_number: number publication in the given year & table_type

    Returns a tuple:
      ``url``             - builded url as string,
      ``cache_file_path`` - path to local cache file that might be used

    Usage::

       >>> from nbp import publication
       >>> publication.build_url(2012, 123, 'a')
       >>> ('http://rss.nbp.pl/kursy/xml2/2012/a/12a123.xml', None)
       >>>
       >>> publication.build_url(2012, 123, 'a', cache_dir='/home/<user>/.nbp/')
       >>> ('http://rss.nbp.pl/kursy/xml2/2012/a/12a123.xml',
       ...  '/home/<user>/.nbp/2012/a/12a123.xml')
    """
    prefix = NBP_CURRENCY_TABLE_URL_PREFIX
    short_year = str(year)[2:]                 # 2012  =>  12
    pub_number = str(pub_number).rjust(3, '0') # 4     =>  004

    params = year, table_type, short_year, table_type, pub_number
    path = NBP_CURRENCY_TABLE_URL_PATTERN % params

    url = '%s%s' % (prefix, path)
    if cache_dir:
        cache_file_path = os.path.join(cache_dir, path)
    else:
        cache_file_path = None
    return (url, cache_file_path)


def gen_urls(year=None, pub_number=None, table_type=None, gen_number=15, cache_dir=None):
    """
    Generator that iterates tuples of (``url``, ``cache_file_path``)
    down over existing publication numbers.

    You can change number of generation via ``gen_number`` kwarg.
    The default value of ``gen_number`` is 15.
    """

    while gen_number > 0:
        if pub_number == 0:  # we're in the begining of the year
            previous_year_date = date(year, 1, 1) - timedelta(days=1)
            year       = previous_year_date.year
            pub_number = calculate_number(previous_year_date, table_type)
        yield build_url(year, pub_number, table_type, cache_dir=cache_dir)
        pub_number -= 1
        gen_number -= 1
# END #######################################################################


TABLE_TYPES_DAY_COUNTER = {
    A : dateutils.count_working_days,
    B : dateutils.count_wednesdays
}

def calculate_number(date, table_type):
    """
    Calculates publication number for the
    given ``date`` and ``table_type``.

    In NBP tables each publication has incremental number
    that depends on ``table_type``.
    """
    assert table_type in TABLE_TYPES
    func = TABLE_TYPES_DAY_COUNTER[table_type.lower()]
    return func(date)


def download(url):
    """
    Tries to download exchange_rate_table for the given url.
    Returns:
      resp on success
      None on failure
    """
    try:
        resp = urllib2.urlopen(url)
        if hasattr(resp, 'getcode') and resp.getcode() == 200:
            return resp
    except urllib2.URLError, e:
        return None


def fetch_data(url, cache_file_path):
    if cache_file_path:
        cache = caching.get_cache(cache_file_path)
        if not cache.dir_exists():
            cache.create_dir()

        if not cache.file_exists():
            data = download(url)
            if data:
                cache.save(data)

        if cache.file_exists():
            return cache.open()
    else:
        return download(url)


def parse(file_, url=None):
    """
    Parses given xml-file-like object.
    """
    dom = minidom.parse(file_)
    dget = dom.getElementsByTagName

    table_no = dget('numer_tabeli')[0].firstChild.data
    pub_date = datetime.strptime(
        dget('data_publikacji')[0].firstChild.data,
        '%Y-%m-%d',
    )
    table = Table(no=table_no, publication_date=pub_date, url=url)

    for elem in dget('pozycja'):
        get = elem.getElementsByTagName

        currency_name = get('nazwa_waluty')[0].firstChild.data
        currency_code = get('kod_waluty')[0].firstChild.data
        scaler        = get('przelicznik')[0].firstChild.data
        rate          = get('kurs_sredni')[0].firstChild.data

        table.set(currency_code, Currency(
            currency_name,
            currency_code,
            float(rate.replace(',', '.')),
            int(scaler),
        ))

    return table


def get_table(date, table_type, cache_dir=None):
    """
    Download and parse latest NBP table for given 'date' and 'table_type'
    """
    urlsgen = gen_urls(
        pub_number = calculate_number(date, table_type),
        year       = date.year,
        table_type = table_type,
        cache_dir  = cache_dir,
    )

    for url, cache_file_path in urlsgen:
        data = fetch_data(url, cache_file_path)
        if data:
            table = parse(data, url=url)
            data.close()
            if not table.publication_date.date() > date:
                return table
    return None


def format_result(nbp_table, currency, search_date):
    currency_obj = nbp_table.get(currency)
    return {
        'search_date' : search_date.strftime('%Y-%m-%d'),
        'table_no'    : nbp_table.no,
        'pub_date'    : nbp_table.publication_date.strftime('%Y-%m-%d'),
        'url'         : nbp_table.url,
        'currency'    : currency_obj.to_dict(rescale_rate=True),
    }


def download_exchange_rate(date, currency, cache_dir=None):
    for table_type in TABLE_TYPES:
        nbp_table = get_table(date, table_type, cache_dir=cache_dir)
        if nbp_table and currency in nbp_table:
            return format_result(nbp_table, currency, date)
    return None
