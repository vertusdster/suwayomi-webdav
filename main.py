import urllib.parse
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.dav_provider import DAVProvider, DAVCollection, _DAVResource
import requests
import io
import os

# 加载 .env 文件中的环境变量
CONTENT_URL = os.getenv('CONTENT_URL', 'http://127.0.0.1:4567/')
API_URL = CONTENT_URL + "/api/graphql"
DUMMY_IMAGE = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
page_resource_cache = {}
headers = {"Content-Type": "application/json"}

# 自定义 MangaDAVProvider，通过 GraphQL 请求漫画、章节和页面数据
class MangaDAVProvider(DAVProvider):
    page_collection_cache = {}
    def __init__(self):
        super().__init__()
        self.manga_name_to_id = {}  # 用于映射 manga 名称到 manga_id
        self.chapter_name_to_id = {}  # 用于映射 chapter 名称到 chapter_id

    def get_resource_inst(self, path, environ):
        # 打印请求路径以供调试
        print(f"Requested path: {path}")
        
        path = path.strip("/")  # 去除多余的斜杠
        parts = path.split("/")
        print(f"Requested parts: {parts}")

        # 根目录显示漫画清单
        if len(parts) == 1 and parts[0] == "":
            print(f"Serving manga collection at root: {path}")
            return MangaCollection(self, "/", environ, self.manga_name_to_id)  # 传递 environ 和 manga_name_to_id
        
        # 漫画目录，显示章节清单
        elif len(parts) == 1 and parts[0] != "":
            manga_name = parts[0]  # 获取漫画名称
            manga_id = self.manga_name_to_id.get(manga_name)
            if manga_id:
                print(f"Serving chapter collection for manga {manga_id} at {path}")
                return ChapterCollection(self, path, manga_name, manga_id, True, environ)
            else:
                print(f"Manga name '{manga_name}' not found.")
        
        # 章节目录，显示页面列表
        elif len(parts) == 2:
            manga_name = parts[0]  # 获取 manga_name
            chapter_name = parts[1]  # 获取章节名称
            chapter_id = self.chapter_name_to_id.get(manga_name + chapter_name)
            if chapter_id:
                print(f"Serving page collection for chapter {chapter_id}  of manga {manga_name} at {path}")
                # 传递 manga_name 到 PageCollection
                return PageCollection(self, path, chapter_id, chapter_name, manga_name, True, environ)
            else:
                print(self.chapter_name_to_id)
                print(f"Chapter name '{chapter_name}' not found.")

        # 页面文件，显示具体页面
        elif len(parts) == 3:
            manga_name = parts[0]
            chapter_name = parts[1]
            page_name_with_extension = parts[2]  # 提取带有.jpg后缀的文件名
            page_number = int(page_name_with_extension.split("_")[1].split(".")[0]) -1  # 提取页面编号
            chapter_id = self.chapter_name_to_id.get(manga_name + chapter_name)
            if chapter_id:
                print(f"Serving page {page_number} for chapter {chapter_id}  of manga {manga_name} at {path}")
                return PageResource(self, path, "", page_number, chapter_id, True, environ)

        return None


# 漫画目录类
class MangaCollection(DAVCollection):

    def __init__(self, provider, path, environ, manga_name_to_id):
        print(f"Initializing MangaCollection with path: {path}")
        path = str(path) or "/"
        if not path.startswith("/"):
            path = "/" + str(path)
        super().__init__(path, environ)
        self.provider = provider
        self.manga_name_to_id = manga_name_to_id
        self.mangas = self._get_mangas()
        

    def _get_mangas(self):
        # 查询漫画清单
        query = """
        query GET_CATEGORY_MANGAS($id: Int!) {
          category(id: $id) {
            mangas {
              nodes {
                id
                title
                author
              }
            }
          }
        }
        """
        variables = {"id": 0}  # 假设类别ID为0
        response = requests.post(API_URL, json={"operationName": "GET_CATEGORY_MANGAS", "variables": variables, "query": query}, headers=headers)
        mangas = response.json()["data"]["category"]["mangas"]["nodes"]

        for manga in mangas:
            self.manga_name_to_id[manga['title']] = manga['id']
        
        return mangas

    def get_member_names(self):
        return [manga['title'] for manga in self.mangas]

    def get_member(self, name):
        manga_id = self.manga_name_to_id.get(name)
        if manga_id:
            return ChapterCollection(self.provider, self.path + name, name, manga_id, False , self.environ)
        else:
            return None
        
    def get_content_type(self):
        # 指定目录的 MIME 类型为 httpd/unix-directory
        return "httpd/unix-directory"

# 章节目录类
class ChapterCollection(DAVCollection):
    def __init__(self, provider, path, manga_name, manga_id, need_download, environ):
        print(f"Initializing ChapterCollection with path: {path}, manga_id: {manga_id}")
        path = "/" + str(path).strip("/")
        super().__init__(path, environ)
        self.provider = provider
        self.manga_name = manga_name
        self.manga_id = manga_id
        self.need_download = need_download
        self.chapters = self._get_chapters()


    def get_content_type(self):
        # 指定目录的 MIME 类型为 httpd/unix-directory
        return "httpd/unix-directory"

    def _get_chapters(self):
        # GraphQL 查询章节列表
        query = """
        fragment FULL_CHAPTER_FIELDS on ChapterType {
          chapterNumber
          fetchedAt
          id
          isBookmarked
          isDownloaded
          isRead
          lastPageRead
          lastReadAt
          mangaId
          manga {
            id
            title
            inLibrary
            thumbnailUrl
            lastFetchedAt
            __typename
          }
          meta {
            key
            value
            __typename
          }
          name
          pageCount
          realUrl
          scanlator
          sourceOrder
          uploadDate
          url
          __typename
        }

        query GET_CHAPTERS($condition: ChapterConditionInput, $orderBy: ChapterOrderBy, $orderByType: SortOrder) {
          chapters(
            condition: $condition
            orderBy: $orderBy
            orderByType: $orderByType
          ) {
            nodes {
              ...FULL_CHAPTER_FIELDS
              __typename
            }
            totalCount
            __typename
          }
        }
        """
        variables = {
            "condition": {"mangaId": self.manga_id},
            "orderBy": "SOURCE_ORDER",
            "orderByType": "DESC"
        }
        if self.need_download:
            response = requests.post(API_URL, json={"operationName": "GET_CHAPTERS", "variables": variables, "query": query}, headers=headers)
            chapters = response.json()["data"]["chapters"]["nodes"]


            # 只使用 `chapter_name` 作为键
            for chapter in chapters:
                self.provider.chapter_name_to_id[self.manga_name + chapter['name']] = chapter['id']
        else:
            chapters= []
        return chapters

    def get_member_names(self):
        return [f"{self.manga_name}/{chapter['name']}" for chapter in self.chapters]

    def get_member(self, name):
        chapter_name = name.replace(f"{self.manga_name}/", "")
        chapter_id = self.provider.chapter_name_to_id.get(self.manga_name + chapter_name)
        if chapter_id:
            return PageCollection(self.provider, "/" + name, chapter_id, chapter_name, self.manga_name ,False , self.environ)
        else:
            return None


# 页面集合类
class PageCollection(DAVCollection):
    def __init__(self, provider, path, chapter_id, chapter_name, manga_name,  need_download , environ):
        print(f"Initializing PageCollection with path: {path}, chapter_id: {chapter_id}")
        path = "/" + str(path).strip("/")
        super().__init__(path, environ)
        self.provider = provider
        self.manga_name = manga_name
        self.chapter_id = chapter_id
        self.need_download = need_download
        self.pages = self._load_pages()
        self.chapter_name = chapter_name

    def get_content_type(self):
        # 指定目录的 MIME 类型为 httpd/unix-directory
        return "httpd/unix-directory"
    
    def _load_pages(self):
        # GraphQL 查询章节页面
        query = """
        mutation GET_CHAPTER_PAGES_FETCH($input: FetchChapterPagesInput!) {
          fetchChapterPages(input: $input) {
            chapter {
              id
              pageCount
            }
            pages
          }
        }
        """
        if self.need_download:
            variables = {"input": {"chapterId": int(self.chapter_id)}}
            response = requests.post(API_URL, json={"operationName": "GET_CHAPTER_PAGES_FETCH", "variables": variables, "query": query}, headers=headers)
            pages = response.json()["data"]["fetchChapterPages"]["pages"]
        else:
            pages = []
        return pages

    def get_member_names(self):
        return [f"{self.manga_name}/{self.chapter_name}/page_{i+1}.jpg" for i in range(len(self.pages))]
    
    def get_member(self, name):
        page_number = int(name.split("_")[1].split(".")[0]) - 1  # 从 page_1.jpg 获取索引 0
        page_url = CONTENT_URL + self.pages[page_number]  # 使用缓存的页面 UR

        # 检查全局缓存中是否已存在该 page_url 对应的 PageResource
        if page_url in page_resource_cache:
            print(f"Using cached PageResource for {page_url}")
            return page_resource_cache[page_url]
        else:
            # 创建新的 PageResource 实例并缓存
            print(f"Creating new PageResource for {page_url}")
            resource = PageResource(self.provider, "/" + name, page_url, page_number, self.chapter_id, False, self.environ)
            page_resource_cache[page_url] = resource
            return resource
        
# 页面资源类
class PageResource(_DAVResource):
    def __init__(self, provider, path, page_url, page_number, chapter_id, need_download, environ):
        print(f"Initializing PageResource with path: {path}, page_url: {page_url}, need_download: {need_download}")
        if not path.startswith("/"):
            path = "/" + str(path)
        super().__init__(path, False, environ)
        self.provider = provider
        self.page_url = page_url
        self.page_number = page_number
        self._content = b""
        self.content_length = 0
        self.chapter_id = chapter_id
        self.need_download = need_download
        self.dummy_image = DUMMY_IMAGE  # 准备一个 Dummy 图片
    def _load_content_mod(self):
        # 下载页面内容并缓存
        if self.need_download:
            if self.page_url == "":
                query = """
                mutation GET_CHAPTER_PAGES_FETCH($input: FetchChapterPagesInput!) {
                  fetchChapterPages(input: $input) {
                    chapter {
                      id
                      pageCount
                    }
                    pages
                  }
                }
                """
                print(f"Loading page url of page number: {self.page_number }")
                variables = {"input": {"chapterId": int(self.chapter_id)}}
                response = requests.post(API_URL, json={"operationName": "GET_CHAPTER_PAGES_FETCH", "variables": variables, "query": query}, headers=headers)
                pages = response.json()["data"]["fetchChapterPages"]["pages"]
                print(pages)
                self.page_url = CONTENT_URL + pages[self.page_number]  # 更新 page_url
            if self._content == b"" or  self._content == self.dummy_image:
                print(f"downloading page content : {self.page_url}")
                response = requests.get(self.page_url)
                self._content = response.content
                self.content_length = len(self._content)
        else:
            if self._content == b"":
                # 如果不需要下载，使用 Dummy 图片
                print("Using dummy image as placeholder")
                self._content = self.dummy_image
                self.content_length = 1048576

    def get_content_length(self):
        self._load_content_mod()
        return self.content_length
    


    def get_content(self):
        self._load_content_mod()
        return io.BytesIO(self._content)

    def get_content_type(self):
        return "image/jpeg"
    

    def support_ranges(self):
        return False

    def support_etag(self):
        return False

    def get_display_info(self):
        return {
            "type": "file",
            "mimetype": "image/jpeg",
        }


# 配置 WsgiDAV 应用程序
config = {
    "provider_mapping": {"/": MangaDAVProvider()},
    "simple_dc": {"user_mapping": {"*": True}},  # 允许所有用户访问
    "verbose": 3,  # 输出更多详细日志,
    "max_propfind_depth": 1,  # 限制 PROPFIND 的最大深度为 1
}

# 启动 WebDAV 服务器
if __name__ == "__main__":
    app = WsgiDAVApp(config)
    from wsgiref.simple_server import make_server
    server = make_server("0.0.0.0", 8080, app)
    print("Serving on port 8080...")
    server.serve_forever()
