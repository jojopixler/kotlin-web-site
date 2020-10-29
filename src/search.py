import os
from os import path
from typing import Dict, List, Iterator

from algoliasearch import algoliasearch
from algoliasearch.index import Index
from bs4 import BeautifulSoup, Tag
from flask import current_app as app
from googleapiclient.discovery import build, Resource
from oauth2client.service_account import ServiceAccountCredentials

from src.api import get_api_page

dist_path = "./dist"
root_folder = path.dirname(path.dirname(__file__))


def get_pages(freezer):
    frozen = freezer._generate_all_urls()

    frozen_dict = dict()

    for url, type in frozen:
        frozen_dict[url] = type

    paths = []

    if os.path.isdir(dist_path):
        for root, dirnames, filenames in os.walk(dist_path):
            for filename in filenames:
                prefix_path = root[len(dist_path):]
                if not prefix_path: prefix_path = "/"

                url = path.join(prefix_path, filename)

                if filename == "index.html":
                    paths.append((prefix_path, frozen_dict.get(prefix_path, None)))
                else:
                    paths.append((url, frozen_dict.get(url, None)))

    return paths if len(paths) > 0 else frozen


def initialize_analyticsreporting() -> Resource:
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        os.environ['KEY_FILE_LOCATION'], scopes='https://www.googleapis.com/auth/analytics.readonly')
    analytics = build('analyticsreporting', 'v4', credentials=credentials)
    return analytics


def get_report(analytics: Resource) -> Dict:
    return analytics.reports().batchGet(
        body={
            "reportRequests":
                [
                    {
                        "viewId": "85132606",
                        "samplingLevel": "LARGE",
                        "filtersExpression": "ga:hostname==kotlinlang.org;ga:pagepath!@?",
                        "pageSize": 10000,
                        "orderBys": [
                            {
                                "fieldName": "ga:uniquepageviews",
                                "sortOrder": "DESCENDING"
                            }
                        ],
                        "dateRanges":
                            [
                                {
                                    "startDate": "30daysAgo",
                                    "endDate": "yesterday"
                                }
                            ],
                        "metrics":
                            [
                                {
                                    "expression": "ga:uniquepageviews",
                                    "alias": ""
                                }
                            ],
                        "dimensions":
                            [
                                {
                                    "name": "ga:pagePath"
                                }
                            ]
                    }
                ]
        }).execute()


def get_page_views_statistic() -> Dict[str, int]:
    print("Acquiring page view statistic from google")
    page_views = {}
    analytics = initialize_analyticsreporting()
    report = get_report(analytics)
    for row in report["reports"][0]["data"]["rows"]:
        page_views[row["dimensions"][0]] = int(row['metrics'][0]["values"][0])
    print("Page view statistic acquired")
    return page_views


def get_client():
    return algoliasearch.Client(os.environ['SEARCH_USER'], os.environ['SEARCH_KEY'])


def get_index() -> Index:
    index_name = os.environ['INDEX_NAME'] if 'INDEX_NAME' in os.environ else "dev_KOTLINLANG"
    return Index(get_client(), index_name)


def get_page_path_from_url(url):
    if url.endswith('.html'):
        return url[1:-5]
    else:
        return url[1:] + "index"


def group_small_content_pats(content_parts, start_index=0):
    size = len(content_parts)
    for i in range(start_index, size):
        if len(content_parts[i]) < 40 and i < size - 1:
            content_parts[i] = content_parts[i].rstrip()
            if not len(content_parts[i]) == 0 and not content_parts[i].endswith("."):
                content_parts[i] = content_parts[i] + ". "
            content_parts[i] = content_parts[i] + content_parts[i + 1].lstrip()
            del content_parts[i + 1]
            group_small_content_pats(content_parts, i)
            return
    if size > 1 and len(content_parts[size - 1]) < 40:
        content_parts[size - 2] = content_parts[size - 2].rstrip()
        if not len(content_parts[size - 2]) == 0 and not content_parts[size - 2].endswith("."):
            content_parts[size - 2] = content_parts[size - 2] + ". "
        content_parts[size - 2] = content_parts[size - 2] + content_parts[size - 1].lstrip()
        del content_parts[size - 1]


def get_valuable_content(page_path, content: Iterator[Tag]) -> List[str]:
    valuable_content = []
    for child in content:
        if not isinstance(child, Tag):
            continue
        if child.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'li', 'span', 'strong', 'aside']:
            valuable_content.append(child.text)
        elif child.name in ['ul', 'ol', 'blockquote', 'div', 'section']:
            valuable_content += get_valuable_content(page_path, child.children)
        elif child.name in ['iframe', 'pre', 'code', 'hr', 'table', 'script', 'link', 'a', 'br', 'i', 'img']:
            continue
        else:
            raise Exception('Unknown tag "' + child.name + '" in ' + page_path)
    group_small_content_pats(valuable_content)
    return valuable_content


def get_page_index_objects(content: Tag, url: str, page_path: str, title: str, page_type: str,
                           page_views: int) -> List[Dict]:
    index_objects = []
    for ind, page_part in enumerate(get_valuable_content(page_path, content.children)):
        page_info = {'url': url, 'objectID': page_path + '#' + str(ind), 'content': page_part,
                     'headings': title, 'type': page_type, 'pageViews': page_views}
        index_objects.append(page_info)
    return index_objects


def get_markdown_page_index_objects(content: Tag, url: str, page_path: str, title: str, page_type: str,
                                    page_views: int) -> List[Dict]:
    headers = ['h1', 'h2', 'h3']
    index_objects = []
    children = [element for element in content.children if isinstance(element, Tag)]
    if len(children) > 0 and children[0].name not in headers:
        return get_page_index_objects(content, url, page_path, title, page_type, page_views)
    block_title = ""
    content = []
    url_with_href = ""
    for child in children:
        if child.name in headers:
            if block_title != '':
                for ind, page_part in enumerate(get_valuable_content(page_path, content)):
                    page_info = {'url': url_with_href, 'objectID': url_with_href + str(ind), 'content': page_part,
                                 'headings': block_title, 'pageTitle': title, 'type': page_type,
                                 'pageViews': page_views}
                    index_objects.append(page_info)
            url_with_href = url + '#' + child.get('id')
            block_title = child.text
            content = []
        else:
            content.append(child)
    return index_objects


def get_wh_index():
    if 'WH_SEARCH_USER' in os.environ and 'WH_SEARCH_KEY' in os.environ:
        client = algoliasearch.Client(os.environ['WH_SEARCH_USER'], os.environ['WH_SEARCH_KEY'])
        index_name = os.environ['WH_INDEX_NAME'] if 'WH_INDEX_NAME' in os.environ else "dev_JETBRAINSCOM_HELP"
        return Index(client, index_name)
    return None


def get_page_content(url):
    path_file = dist_path + url

    if path.exists(path_file):
        with open(path_file, 'r', encoding="UTF-8") as file:
            return file.read()

    client = app.test_client()
    content = client.get(url, follow_redirects=True)

    if content.status_code != 200:
        raise Exception('Bad response during indexing')

    return content.data


def to_wh_index(item):
    page_title = item["pageTitle"] if "pageTitle" in item else item["headings"]

    return {
        "objectID": item["objectID"],
        "headings": item["headings"],
        "mainTitle": page_title,
        "pageTitle": page_title,
        "content": item["content"],
        "url": "https://kotlinlang.org" + item["url"],
        "metaDescription": "",
        "type": "Documentation",
        "parent": item["url"],
        "pageViews": item["pageViews"],
        "product": "help/kotlin-reference",
        "version": "1.4.10",
        "breadcrumbs": None,
    }


def build_search_indices(pages):
    page_views_statistic = [] #get_page_views_statistic()

    index_objects = []
    wh_index_objects = []

    print("Start building index")
    for url, endpoint in pages:
        if url.endswith('/'): url += 'index.html'
        if not url.endswith('.html'): continue

        title = ''
        content = ''
        page_type = 'Page'
        page_path = get_page_path_from_url(url)
        page_views = 0
        page_index_parser = get_markdown_page_index_objects

        if url in page_views_statistic:
            page_views = page_views_statistic[url]

        if page_path.startswith('community'):
            page_type = 'Community'
        elif page_path.startswith('docs/reference'):
            page_type = 'Reference'
        elif page_path.startswith('docs/tutorials'):
            page_type = 'Tutorial'

        if page_path.startswith("api/latest/"):
            page_info = get_api_page(True, page_path[4:], dist_path)

            for table in page_info['content']('table'):
                table.extract()

            for overload_group in page_info['content'].findAll("div", {"class": "signature"}):
                overload_group.extract()

            breadcrumbs = page_info['content'].find("div", {"class": "api-docs-breadcrumbs"})

            title = page_info['title']

            if breadcrumbs is not None:
                full_name_parts = list(map(lambda link: link.text, breadcrumbs.findAll("a")))

                if "kotlin-stdlib" in full_name_parts:
                    full_name_parts.remove("kotlin-stdlib")
                else:
                    full_name_parts.remove("kotlin.test")

                title = " › ".join(full_name_parts).replace('<', '&lt;').replace('>', '&gt;')
                breadcrumbs.extract()

            page_type = "Standard Library" if "jvm/stdlib" in url else "Kotlin Test"
            content = page_info['content'].find('article', {"role": "main"})
            page_index_parser = get_page_index_objects
        else:
            html_content = get_page_content(url)
            parsed = BeautifulSoup(html_content, "html.parser")

            if parsed.find("meta", {"http-equiv": "refresh"}):
                continue

            if parsed.select("body[data-article-props]"):
                page_type = "Documentation"

            if not title:
                title_node = parsed.find("title")
                if title_node:
                    title = title_node.text

            # Our default pages
            content = parsed.find("div", {"class": "page-content"})

            # Our modern pages
            if content is None:
                content = parsed.find("article", {"class": "page-content"})

            # WebHelp pages
            if content is None:
                content = parsed.find("article", {"class": "article"})

        if title and content:
            print("processing " + url + ' - ' + page_type)

            page_indices = page_index_parser(
                content,
                url,
                page_path,
                title,
                page_type,
                page_views
            )

            index_objects += page_indices
            wh_index_objects += list(map(to_wh_index, page_indices))
        else:
            print('skip: ' + url + ' unknown page content in with title: ' + title)

    wh_index = get_wh_index()

    if wh_index:
        print("Submitting WH index objects to " + wh_index.index_name + " index")
        wh_index.add_objects(wh_index_objects)

    print("Index objects successfully built")

    index = get_index()
    print("Submitting index objects to " + index.index_name + " index")
    index.add_objects(index_objects)
