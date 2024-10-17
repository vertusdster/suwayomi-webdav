import urllib.parse
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.dav_provider import DAVProvider, DAVCollection, _DAVResource
import requests
import io

# 更新的 API 基础路径
API_URL = "http://127.0.0.1:4567/api/graphql"
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
                return PageResource(self, path, chapter_id, page_number, environ)  # 传递 environ

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


# 页面目录类
class PageCollection(DAVCollection):
    def __init__(self, provider, path, chapter_id, environ):
        # 打印初始化信息以供调试
        print(f"Initializing PageCollection with path: {path}, chapter_id: {chapter_id}")
        
        # 确保路径正确，转换为字符串并处理
        path = "/" + str(path)
        print("PageCollection path: " + path)
        super().__init__(path, environ)  # 正确传递 environ
        self.provider = provider
        self.chapter_id = chapter_id
        self.pages = None  # 在初始化时不加载页面
        self.environ = environ

    def get_member_names(self):
        if self.pages is None:
            # 只有打开章节目录时，才会按需加载页面
            self.pages = self._get_pages()
        return [f"page_{i}" for i in range(len(self.pages))]

    def _get_pages(self):
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
        return response.json()["data"]["fetchChapterPages"]["pages"]

    def get_member(self, name):
        page_number = name.split("_")[1]
        return PageResource(self.provider, self.path + name, self.chapter_id, page_number, self.environ)


# 页面资源类
class PageResource(_DAVResource):  # 使用 _DAVResource 而不是 DAVResource
    def __init__(self, provider, path, chapter_id, page_number, environ):
        # 打印初始化信息以供调试
        print(f"Initializing PageResource with path: {path}, chapter_id: {chapter_id}, page_number: {page_number}")
        
        # 确保路径为字符串
        path = "/" + str(path)
        print("PageResource path: " + path)
        super().__init__(path,False, environ)  # 正确传递 environ
        self.provider = provider
        self.chapter_id = chapter_id
        self.page_number = page_number
        self.page_url = self._get_page_url()

    def _get_page_url(self):
        query = """
        mutation GET_CHAPTER_PAGES_FETCH($input: FetchChapterPagesInput!) {
          fetchChapterPages(input: $input) {
            pages
          }
        }
        """
        variables = {"input": {"chapterId": int(self.chapter_id)}}
        response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers)
        pages = response.json()["data"]["fetchChapterPages"]["pages"]
        return pages[int(self.page_number)]

    def get_content_length(self):
        return None

    def get_content(self):
        # 获取页面内容 (图片等)
        response = requests.get(self.page_url)
        return io.BytesIO(response.content)

    def get_display_info(self):
        return {
            "type": "file",
            "mimetype": "image/jpeg",
        }

    def get_content_type(self):
        # 返回 MIME 类型，例如 image/jpeg
        return "image/jpeg"
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
