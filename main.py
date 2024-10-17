import urllib.parse
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.dav_provider import DAVProvider, DAVCollection, _DAVResource
import requests
import io

# 更新的 API 基础路径
API_URL = "http://127.0.0.1:4567/api/graphql"
CONTENT_URL = "http://127.0.0.1:4567/"
headers = {"Content-Type": "application/json"}

# 自定义 MangaDAVProvider，通过 GraphQL 请求章节和页面数据
class MangaDAVProvider(DAVProvider):
    def __init__(self):
        super().__init__()
        self.chapter_name_to_id = {}  # 用于映射chapter name到chapter_id

    def get_resource_inst(self, path, environ):
        # 打印请求路径以供调试
        print(f"Requested path: {path}")
        
        path = path.strip("/")  # 去除多余的斜杠
        parts = path.split("/")
        print(f"Requested parts: {parts}")

        # 根目录显示章节列表
        if len(parts) == 1 and parts[0] == "":
            print(f"Serving chapter collection at root: {path}")
            return ChapterCollection(self, "/", environ, self.chapter_name_to_id)  # 传递 environ 和 name->id 映射
        
        # 章节目录，通过章节名称查找chapter_id
        elif len(parts) == 1 and parts[0] != "":
            chapter_name = parts[0] # 解码路径中的特殊字符
            print("find chaptername of : " + chapter_name)
            chapter_id = self.chapter_name_to_id.get(chapter_name)
            if chapter_id:
                print(f"Serving page collection for chapter {chapter_id} at {path}")
                return PageCollection(self, path, chapter_id, environ)  # 传递 environ
            else:
                print(f"Chapter name '{chapter_name}' not found.")
        
        # 页面文件
        elif len(parts) == 2:
            chapter_name = parts[0]  # 解码路径中的特殊字符
            print("find chaptername of : " + chapter_name)
            chapter_id = self.chapter_name_to_id.get(chapter_name)
            page_number = parts[1].split("_")[1]
            print("find page_number of : " + page_number)
            if chapter_id:
                print(f"Serving page {page_number} for chapter {chapter_id} at {path}")
                return PageResource(self, path, page_number, environ)  # 传递 environ

        return None


# 章节目录类
class ChapterCollection(DAVCollection):
    def __init__(self, provider, path, environ, chapter_name_to_id):
        # 打印初始化信息以供调试
        print(f"Initializing ChapterCollection with path: {path}")
        
        # 确保传入的路径为有效字符串
        path = str(path) or "/"
        super().__init__(path, environ)  # 正确传递 environ
        self.provider = provider
        self.chapter_name_to_id = chapter_name_to_id
        self.chapters = self._get_chapters()

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

        fragment PAGE_INFO on PageInfo {
          endCursor
          hasNextPage
          hasPreviousPage
          startCursor
          __typename
        }

        query GET_CHAPTERS($after: Cursor, $before: Cursor, $condition: ChapterConditionInput, $filter: ChapterFilterInput, $first: Int, $last: Int, $offset: Int, $orderBy: ChapterOrderBy, $orderByType: SortOrder) {
          chapters(
            after: $after
            before: $before
            condition: $condition
            filter: $filter
            first: $first
            last: $last
            offset: $offset
            orderBy: $orderBy
            orderByType: $orderByType
          ) {
            nodes {
              ...FULL_CHAPTER_FIELDS
              __typename
            }
            pageInfo {
              ...PAGE_INFO
              __typename
            }
            totalCount
            __typename
          }
        }
        """
        variables = {
            "condition": {"mangaId": 3},
            "orderBy": "SOURCE_ORDER",
            "orderByType": "DESC"
        }
        response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers)
        chapters = response.json()["data"]["chapters"]["nodes"]

        # 构建 chapter_name -> chapter_id 映射
        for chapter in chapters:
            self.chapter_name_to_id[chapter['name']] = chapter['id']
        
        return chapters

    def get_member_names(self):
        # 使用 URL 编码后的章节名称作为目录名
        return [chapter['name'] for chapter in self.chapters]

    def get_member(self, name):
        # 使用解码后的章节名称查找对应的 chapter_id
        print("get member:" + name)
        chapter_name = name
        chapter_id = self.chapter_name_to_id.get(chapter_name)
        if chapter_id:
            return PageCollection(self.provider, self.path + name, chapter_id, self.environ)
        else:
            return None

class PageCollection(DAVCollection):
    def __init__(self, provider, path, chapter_id, environ):
        # 打印初始化信息以供调试
        print(f"Initializing PageCollection with path: {path}, chapter_id: {chapter_id}")
        
        # 确保路径正确，转换为字符串并处理
        path = "/" + str(path)
        super().__init__(path, environ)  # 正确传递 environ
        self.provider = provider
        self.chapter_id = chapter_id
        self.pages = []
       

    def _load_pages(self):
        """加载页面数据，并缓存结果"""
        print(f"Fetching pages for chapter {self.chapter_id}")
        # GraphQL 查询章节页面
        query = """
        mutation GET_CHAPTER_PAGES_FETCH($input: FetchChapterPagesInput!) {
          fetchChapterPages(input: $input) {
            clientMutationId
            chapter {
              id
              pageCount
              __typename
            }
            pages
            __typename
          }
        }
        """
        variables = {"input": {"chapterId": int(self.chapter_id)}}
        response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers)
        pages = response.json()["data"]["fetchChapterPages"]["pages"]
        return pages

    def get_member_names(self):
        """返回所有页面的名称"""
        if not self.pages:
            self.pages = self._load_pages()  # 调用 API 获取页面数据
        return [f"page_{i}" for i in range(len(self.pages))]

    def get_member(self, name):
        """根据页面名称返回 PageResource 实例，使用缓存的页面 URL"""
        if not self.pages:
            self.pages = self._load_pages()  # 调用 API 获取页面数据
        page_number = int(name.split("_")[1])  # 从页面名称中提取页面编号
        page_url = CONTENT_URL + self.pages[page_number]  # 使用缓存的页面 URL
    
        return PageResource(self.provider, self.path + name, page_url, self.environ)
    

class PageResource(_DAVResource):
    def __init__(self, provider, path, page_url, environ):
        # 打印初始化信息以供调试
        print(f"Initializing PageResource with path: {path}, page_url: {page_url}")
        
        # 确保路径为字符串
        path = "/" + str(path)
        super().__init__(path,False, environ)  # 正确传递 environ
        self.provider = provider
        self.page_url = page_url  # 使用从 PageCollection 传递过来的页面 URL
        self._content = None  # 用于缓存页面内容

    def _load_content(self):
        # 下载页面内容 (图片等) 并缓存
        print(f"start downloading : " + self.page_url)
        response = requests.get(self.page_url)
        self._content = response.content

    def get_content_length(self):
        if self._content is None:
            self._load_content()
        return len(self._content)  # 返回内容长度

    def get_content(self):
        if self._content is None:
            self._load_content()
        return io.BytesIO(self._content)  # 返回页面内容

    def get_content_type(self):
        return "image/jpeg"

    def support_ranges(self):
        return False

    def support_etags(self):
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
    "verbose": 2,
}

# 启动 WebDAV 服务器
if __name__ == "__main__":
    app = WsgiDAVApp(config)
    from wsgiref.simple_server import make_server
    server = make_server("0.0.0.0", 8080, app)
    print("Serving on port 8080...")
    server.serve_forever()
