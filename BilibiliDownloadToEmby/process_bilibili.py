"""
主文件 包含工具类和主类
"""
import asyncio
import logging
import os
import shutil
import sys
import time
import traceback

import ffmpeg
import httpx
import pypinyin
import tenacity
from bilibili_api import video, Credential, HEADERS, exceptions
from lxml import etree
from mbot.openapi import mbot_api

from .constant import SESSDATA, BILI_JCT, BUVID3
from .mr_api import *

_LOGGER = logging.getLogger(__name__)
# _LOGGER = loguru.logger
# server = MovieBotServer(AccessKeySession(SERVER_URL, ACCESS_KEY))
local_path = os.path.split(os.path.realpath(__file__))[0]
server = mbot_api


class BilibiliVideoProcess:
    """bilibili视频下载入库刮削实现类 调用process即可完成单个bv号的下载入库刮削"""

    def __init__(self, video_id: str, media_path: str, emby_persons_path: str = None, if_get_character: bool = False):
        """初始化 Bilibili 类

        :param video_id: 视频id
        :param emby_persons_path: emby人物路径
        :param if_get_character: 是否获取角色信息
        :param media_path: 媒体路径
        """
        self.media_path = media_path
        self.if_get_character = if_get_character
        self.emby_persons_path = emby_persons_path
        self.video_id = video_id
        self.credential = Credential(sessdata=SESSDATA, bili_jct=BILI_JCT, buvid3=BUVID3)
        self.video_info = None
        _LOGGER.info(
            f"开始处理视频 {video_id}，emby人物路径为 {emby_persons_path}， 媒体路径为 {media_path}， 是否获取角色信息为 {if_get_character}")

    async def _get_video_info(self):
        """获取视频信息"""
        v = video.Video(bvid=self.video_id, credential=self.credential)
        self.video_info = await v.get_info()

    async def _download_video(self):
        """下载视频"""
        try:
            v = video.Video(bvid=self.video_id, credential=self.credential)
            raw_year = time.strftime("%Y", time.localtime(self.video_info["pubdate"]))
            if not os.path.exists(f"{local_path}/{self.video_info['title']} ({raw_year})"):
                os.makedirs(f"{local_path}/{self.video_info['title']} ({raw_year})", exist_ok=True)
            url = await v.get_download_url(0)
            video_url = url["dash"]["video"][0]['baseUrl']
            audio_url = url["dash"]["audio"][0]['baseUrl']
            _LOGGER.info(f"收到视频 {self.video_info['title']} 下载请求，开始下载到临时文件夹")
            path = f'{local_path}/{self.video_info["title"]} ({raw_year})/video_temp.m4s'
            res = await DownloadFunc(video_url, path).download_from_url()
            if res:
                _LOGGER.info(f"视频 {self.video_info['title']} 下载完成")
            else:
                Utils.write_error_video(self.video_info)
                Utils.delete_video_folder(self.video_info)
                return None
            path = f'{local_path}/{self.video_info["title"]} ({raw_year})/audio_temp.m4s'
            res = await DownloadFunc(audio_url, path).download_from_url()
            if res:
                _LOGGER.info(f"音频 {self.video_info['title']} 下载完成")
            else:
                Utils.write_error_video(self.video_info)
                Utils.delete_video_folder(self.video_info)
                return None
            _LOGGER.info("音频下载完成")
            in_video = ffmpeg.input(f'{local_path}/{self.video_info["title"]} ({raw_year})/video_temp.m4s')
            in_audio = ffmpeg.input(f'{local_path}/{self.video_info["title"]} ({raw_year})/audio_temp.m4s')
            ffmpeg.output(in_video, in_audio,
                          f'{local_path}/{self.video_info["title"]} ({raw_year})/{self.video_info["title"]} ({raw_year}).mp4',
                          vcodec='copy', acodec='copy', loglevel="error").run(overwrite_output=True)
            os.remove(f"{local_path}/{self.video_info['title']} ({raw_year})/video_temp.m4s")
            os.remove(f"{local_path}/{self.video_info['title']} ({raw_year})/audio_temp.m4s")
            _LOGGER.info(f"视频音频下载完成，已混流为mp4文件，文件名：{self.video_info['title']} ({raw_year}).mp4")
        except Exception as e:
            _LOGGER.error(f"视频 {self.video_info['title']} 下载失败，已记录视频id，稍后重试")
            Utils.write_error_video(self.video_info)
            Utils.delete_video_folder(self.video_info)
            tracebacklog = traceback.format_exc()
            _LOGGER.error(f"报错原因：{tracebacklog}")

    async def _download_video_cover(self):
        """下载视频封面"""
        if Utils.read_error_video(self.video_info):
            return
        _LOGGER.info("开始下载视频封面")
        raw_year = time.strftime("%Y", time.localtime(self.video_info["pubdate"]))
        path = f'{local_path}/{self.video_info["title"]} ({raw_year})/poster.jpg'
        res = await DownloadFunc(self.video_info["pic"], path).download_from_url()
        if res:
            _LOGGER.info("视频封面下载完成")
        else:
            Utils.write_error_video(self.video_info)
            Utils.delete_video_folder(self.video_info)
            return None

    async def _gen_video_nfo(self):
        """生成视频nfo文件"""
        try:
            if Utils.read_error_video(self.video_info):
                return
            _LOGGER.info("开始生成视频nfo文件")
            video_info = self.video_info
            raw_year = time.strftime("%Y", time.localtime(video_info["pubdate"]))
            root = etree.Element("video")
            title = etree.SubElement(root, "title")
            title.text = video_info["title"]
            plot = etree.SubElement(root, "plot")
            plot.text = video_info["desc"]
            year = etree.SubElement(root, "year")
            year.text = time.strftime("%Y", time.localtime(video_info["pubdate"]))
            premiered = etree.SubElement(root, "premiered")
            premiered.text = time.strftime("%Y-%m-%d", time.localtime(video_info["pubdate"]))
            studio = etree.SubElement(root, "studio")
            studio.text = video_info["owner"]["name"]
            id = etree.SubElement(root, "id")
            id.text = video_info["bvid"]
            genre = etree.SubElement(root, "genre")
            genre.text = video_info["tname"]
            runtime = etree.SubElement(root, "runtime")
            runtime.text = str(int(video_info["duration"] / 60))
            try:
                for character in video_info["staff"]:
                    actor = etree.SubElement(root, "actor")
                    name = etree.SubElement(actor, "name")
                    name.text = character["name"]
                    role = etree.SubElement(actor, "role")
                    role.text = character["title"]
                    mid = etree.SubElement(actor, "bilibili_id")
                    mid.text = str(character["mid"])
            except KeyError:
                actor = etree.SubElement(root, "actor")
                name = etree.SubElement(actor, "name")
                name.text = video_info["owner"]["name"]
                type = etree.SubElement(actor, "type")
                type.text = "UP主"
                mid = etree.SubElement(actor, "bilibili_id")
                mid.text = str(video_info["owner"]["mid"])
            tree = etree.ElementTree(root)
            path = f"{local_path}/{self.video_info['title']} ({raw_year})/{self.video_info['title']} ({raw_year}).nfo"
            tree.write(path, encoding="utf-8", pretty_print=True, xml_declaration=True)
            _LOGGER.info("视频nfo文件生成完成")
        except Exception as e:
            _LOGGER.error(f"视频 {self.video_info['title']} nfo文件生成失败，已记录视频id，稍后重试")
            Utils.write_error_video(self.video_info)
            Utils.delete_video_folder(self.video_info)
            tracebacklog = traceback.format_exc()
            _LOGGER.error(f"报错原因：{tracebacklog}")

    async def _gen_character_nfo(self):
        """生成up主信息 当前问题：以英文开头的up主生成的nfo无法被emby识别"""
        try:
            if Utils.read_error_video(self.video_info):
                return
            _LOGGER.info("开始生成up主nfo信息")
            video_info = self.video_info
            raw_year = time.strftime("%Y", time.localtime(video_info["pubdate"]))
            os.makedirs(f"{local_path}/{self.video_info['title']} ({raw_year})/character", exist_ok=True)
            try:
                for character in video_info["staff"]:
                    os.makedirs(f"{local_path}/{self.video_info['title']} ({raw_year})/character/{character['name']}",
                                exist_ok=True)
                    root = etree.Element("person")
                    title = etree.SubElement(root, "title")
                    title.text = character["name"]
                    sorttitle = etree.SubElement(root, "sorttitle")
                    sorttitle.text = ''.join(pypinyin.lazy_pinyin(character["name"], style=pypinyin.Style.FIRST_LETTER))
                    mid = etree.SubElement(root, "bilibili_id")
                    mid.text = str(character["mid"])
                    type = etree.SubElement(root, 'uniqueid', type="bilibili_id")
                    type.text = str(character["mid"])
                    tree = etree.ElementTree(root)
                    path = f"{local_path}/{self.video_info['title']} ({raw_year})/character/{character['name']}/person.nfo"
                    tree.write(str(path), encoding="utf-8", pretty_print=True, xml_declaration=True)
                    _LOGGER.info(f"up主{character['name']}信息生成完成")
            except KeyError:
                os.makedirs(
                    f"{local_path}/{self.video_info['title']} ({raw_year})/character/{video_info['owner']['name']}",
                    exist_ok=True)
                root = etree.Element("person")
                title = etree.SubElement(root, "title")
                title.text = video_info["owner"]["name"]
                sorttitle = etree.SubElement(root, "sorttitle")
                sorttitle.text = ''.join(
                    pypinyin.lazy_pinyin(video_info["owner"]["name"], style=pypinyin.Style.FIRST_LETTER))
                mid = etree.SubElement(root, "bilibili_id")
                mid.text = str(video_info["owner"]["mid"])
                type = etree.SubElement(root, 'uniqueid', type="bilibili_id")
                type.text = str(video_info["owner"]["mid"])
                tree = etree.ElementTree(root)
                path = f"{local_path}/{self.video_info['title']} ({raw_year})/character/{video_info['owner']['name']}/person.nfo"
                tree.write(str(path), encoding="utf-8", pretty_print=True, xml_declaration=True)
                _LOGGER.info(f"up主{video_info['owner']['name']}信息生成完成")
            _LOGGER.info("up主nfo信息生成完成")
        except Exception as e:
            _LOGGER.error(f"up主nfo信息生成失败，已记录视频id，稍后重试")
            Utils.write_error_video(self.video_info)
            Utils.delete_video_folder(self.video_info)
            tracebacklog = traceback.format_exc()
            _LOGGER.error(f"报错原因：{tracebacklog}")

    async def _download_character_folder(self):
        """下载up主头像"""
        if Utils.read_error_video(self.video_info):
            return
        _LOGGER.info("开始下载up主头像")
        video_info = self.video_info
        raw_year = time.strftime("%Y", time.localtime(video_info["pubdate"]))
        try:
            for character in video_info["staff"]:
                path = f'{local_path}/{self.video_info["title"]} ({raw_year})/character/{character["name"]}/folder.jpg'
                _LOGGER.info(f"开始下载up主{character['name']}头像")
                res = await DownloadFunc(character["face"], path).download_from_url()
                if res:
                    _LOGGER.info(f"up主{character['name']}头像下载完成")
                else:
                    _LOGGER.error(f"up主头像下载失败，已记录视频id，稍后重试")
                    Utils.write_error_video(self.video_info)
                    Utils.delete_video_folder(self.video_info)
        except KeyError:
            _LOGGER.info(f"开始下载up主{video_info['owner']['name']}头像")
            path = f'{local_path}/{self.video_info["title"]} ({raw_year})/character/{video_info["owner"]["name"]}/folder.jpg'
            res = await DownloadFunc(video_info["owner"]["face"], path).download_from_url()
            if res:
                _LOGGER.info("up主头像下载完成")
            else:
                _LOGGER.error(f"up主头像下载失败，已记录视频id，稍后重试")
                Utils.write_error_video(self.video_info)
                Utils.delete_video_folder(self.video_info)

    async def _move_character_folder(self):
        """移动up主信息到emby演员文件夹"""
        try:
            if Utils.read_error_video(self.video_info):
                return
            emby_persons_path = self.emby_persons_path
            video_info = self.video_info
            _LOGGER.info(f"开始移动up主头像到emby演员文件夹：{emby_persons_path}")
            _LOGGER.warning("以英文开头的up主名字的头像无法被emby识别，头像显示不出属正常情况")
            raw_year = time.strftime("%Y", time.localtime(video_info["pubdate"]))
            try:
                for character in video_info["staff"]:
                    _LOGGER.info(f"开始移动up主{character['name']}")
                    if not os.path.exists(f"{emby_persons_path}/{character['name'][0]}"):
                        os.makedirs(f"{emby_persons_path}/{character['name'][0]}", exist_ok=True)
                        shutil.move(
                            f"{local_path}/{self.video_info['title']} ({raw_year})/character/{character['name']}",
                            f"{emby_persons_path}/{character['name'][0]}")
                        _LOGGER.info(
                            f"{local_path}/{self.video_info['title']} ({raw_year})/character/{character['name']} -> {emby_persons_path}/{character['name'][0]}")
                    elif not os.path.exists(f"{emby_persons_path}/{character['name'][0]}/{character['name']}"):
                        shutil.move(
                            f"{local_path}/{self.video_info['title']} ({raw_year})/character/{character['name']}",
                            f"{emby_persons_path}/{character['name'][0]}")
                        _LOGGER.info(
                            f"{local_path}/{self.video_info['title']} ({raw_year})/character/{character['name']} -> {emby_persons_path}/{character['name'][0]}")
                    else:
                        _LOGGER.info(f"up主{character['name']}数据已存在，跳过")
            except KeyError:
                _LOGGER.info(f"开始移动up主{video_info['owner']['name']}")
                if not os.path.exists(f"{emby_persons_path}/{video_info['owner']['name'][0]}"):
                    os.makedirs(f"{emby_persons_path}/{video_info['owner']['name'][0]}", exist_ok=True)
                    shutil.move(
                        f"{local_path}/{self.video_info['title']} ({raw_year})/character/{video_info['owner']['name']}",
                        f"{emby_persons_path}/{video_info['owner']['name'][0]}")
                    _LOGGER.info(
                        f"{local_path}/{self.video_info['title']} ({raw_year})/character/{video_info['owner']['name']} -> {emby_persons_path}/{video_info['owner']['name'][0]}")
                elif not os.path.exists(
                        f"{emby_persons_path}/{video_info['owner']['name'][0]}/{video_info['owner']['name']}"):
                    shutil.move(
                        f"{local_path}/{self.video_info['title']} ({raw_year})/character/{video_info['owner']['name']}",
                        f"{emby_persons_path}/{video_info['owner']['name'][0]}")
                    _LOGGER.info(
                        f"{local_path}/{self.video_info['title']} ({raw_year})/character/{video_info['owner']['name']} -> {emby_persons_path}/{video_info['owner']['name'][0]}")
                else:
                    _LOGGER.info(f"up主{video_info['owner']['name']}数据已存在，跳过")
            finally:
                shutil.rmtree(f'{local_path}/{self.video_info["title"]} ({raw_year})/character')
            _LOGGER.info("up主头像移动完成")
        except Exception as e:
            _LOGGER.error(f"up主头像移动失败，已记录视频id，稍后重试")
            Utils.write_error_video(self.video_info)
            Utils.delete_video_folder(self.video_info)
            tracebacklog = traceback.format_exc()
            _LOGGER.error(f"报错原因：{tracebacklog}")

    async def _move_video_folder(self):
        """移动视频文件夹到指定媒体库文件夹"""
        try:
            if Utils.read_error_video(self.video_info):
                return
            emby_videos_path = self.media_path
            video_info = self.video_info
            raw_year = time.strftime("%Y", time.localtime(video_info["pubdate"]))
            _LOGGER.info(f"开始移动视频文件夹到指定媒体文件夹{emby_videos_path}")
            if not os.path.exists(f"{emby_videos_path}/bilibili") and not os.path.exists(
                    f"{emby_videos_path}/bilibili/{self.video_info['title']} ({raw_year})"):
                _LOGGER.info(f"移动{local_path}/{self.video_info['title']} ({raw_year})到{emby_videos_path}/bilibili")
                os.makedirs(f"{emby_videos_path}/bilibili", exist_ok=True)
                shutil.move(f'{local_path}/{self.video_info["title"]} ({raw_year})', f"{emby_videos_path}/bilibili")
            elif os.path.exists(f"{emby_videos_path}/bilibili/{self.video_info['title']} ({raw_year})"):
                _LOGGER.warning(f"{local_path}/{self.video_info['title']} ({raw_year})已存在，覆盖掉")
                shutil.rmtree(f"{emby_videos_path}/bilibili/{self.video_info['title']} ({raw_year})")
                shutil.move(f'{local_path}/{self.video_info["title"]} ({raw_year})', f"{emby_videos_path}/bilibili")
            else:
                _LOGGER.info(f"移动{local_path}/{self.video_info['title']} ({raw_year})到{emby_videos_path}/bilibili")
                shutil.move(f'{local_path}/{self.video_info["title"]} ({raw_year})', f"{emby_videos_path}/bilibili")
            _LOGGER.info("视频文件夹移动完成")
        except Exception as e:
            _LOGGER.error(f"视频文件夹移动失败，已记录视频id，稍后重试")
            Utils.write_error_video(self.video_info)
            Utils.delete_video_folder(self.video_info)
            tracebacklog = traceback.format_exc()
            _LOGGER.error(f"报错原因：{tracebacklog}")

    async def process(self):
        """运行入口函数"""
        if not os.path.exists(f"{local_path}/error_video.txt"):
            with open(f"{local_path}/error_video.txt", "w") as f:
                f.write("该文件用于记录下载失败的视频id，以便下次重试，请勿删除\n")
        try:
            await self._get_video_info()
        except exceptions.ArgsException as e:
            _LOGGER.error(f"参数错误：{e}")
            _LOGGER.error("请重新输入bv号再试！")
            return
        if Utils.read_error_video(self.video_info):
            return
        await self._download_video()
        await self._download_video_cover()
        await self._gen_video_nfo()
        if self.if_get_character:
            await self._gen_character_nfo()
            await self._download_character_folder()
            await self._move_character_folder()
        await self._move_video_folder()
        if Utils.read_error_video(self.video_info):
            return
        _LOGGER.info(f"视频{self.video_info['title']}下载刮削完成，已发送下载完成通知，请刷新emby媒体库")
        Notify(self.video_info).send_all_way()


class Utils:
    """工具类"""

    @staticmethod
    def progress_bar(current, total):
        """进度条"""
        rate = current / int(total)
        rate_num = int(rate * 100)
        r = '\r[%s%s]%d%%' % ("=" * rate_num, " " * (100 - rate_num), rate_num,)
        sys.stdout.write(r)
        sys.stdout.flush()

    @staticmethod
    def write_error_video(video_info):
        """记录下载失败的视频"""
        with open(f"{local_path}/error_video.txt", "a") as f:
            f.write(f"{video_info['bvid']}\n")

    @staticmethod
    def read_error_video(video_info):
        """读取下载失败的视频"""
        with open(f"{local_path}/error_video.txt", "r") as f:
            error_video = f.readlines()
            if error_video:
                if f"{video_info['bvid']}\n" in error_video:
                    return True
                else:
                    return False
            else:
                return False

    @staticmethod
    def remove_error_video(video_info):
        """删除下载失败的视频记录"""
        with open(f"{local_path}/error_video.txt", "r") as f:
            lines = f.readlines()
        with open(f"{local_path}/error_video.txt", "w") as f_w:
            for line in lines:
                if video_info["bvid"] not in line:
                    f_w.write(line)

    @staticmethod
    def get_error_video_list():
        """获取下载失败的视频列表"""
        with open(f"{local_path}/error_video.txt", "r") as f:
            lines = f.readlines()
        error_video_list = []
        for line in lines:
            error_video_list.append(line.replace("\n", ""))
        return error_video_list

    @staticmethod
    def if_get_character():
        """获取mr刮削配置，判断是否获取角色信息"""
        api = ScraperApi(server.session)
        resp = api.config()
        if resp.get('use_cn_person_name'):
            return True, resp.get('person_nfo_path')
        else:
            return False, None

    @staticmethod
    def get_media_path():
        """获取mr媒体路径（识别逻辑：优先选择带有bilibili的媒体路径，其次选择最靠前的movie类型的路径），如果都没有就返回第一个路径"""
        api = MediaPath(server.session)
        resp = api.config()
        for i in resp.get('paths'):
            if 'bilibili' in i.get('target_dir') or 'Bilibili' in i.get('target_dir') or 'BILIBILI' in i.get(
                    'target_dir'):
                return i.get('target_dir')
            elif i.get('type') == 'movie':
                return i.get('target_dir')
        return resp.get('paths')[0].get('target_dir')

    @staticmethod
    def delete_video_folder(video_info):
        """删除视频目录"""
        try:
            raw_year = time.strftime("%Y", time.localtime(video_info["pubdate"]))
            shutil.rmtree(f"{local_path}/{video_info['title']} ({raw_year})")
        except Exception as e:
            _LOGGER.error(f"删除视频目录失败")
            tracebacklog = traceback.format_exc()
            _LOGGER.error(f"报错原因：{tracebacklog}")


def retry_video():
    """重试下载之前失败的视频 被定时任务调用 每次最多重试5个 防止被封ip"""
    error_video_list = Utils.get_error_video_list()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    tasks = []
    i = 0
    for error_video in error_video_list and i < 5:
        _LOGGER.info(f"开始重试下载失败的视频{error_video}")
        if_people_path, people_path = Utils.if_get_character()
        media_path = Utils.get_media_path()
        Utils.remove_error_video({"bvid": error_video})
        tasks.append(BilibiliVideoProcess(error_video, if_get_character=if_people_path, media_path=media_path,
                                          emby_persons_path=people_path).process())
        _LOGGER.info(f"重试下载失败的视频 {error_video} 任务已提交")
        i += 1
    loop.run_until_complete(asyncio.wait(tasks))


# class ListenUploadVideo:
#     """查询用户是否发新视频，配合定时任务使用"""
#     def __init__(self, uid, if_get_character=False, media_path=None, emby_persons_path=None):
#         self.uid = uid
#         self.if_get_character = if_get_character
#         self.media_path = media_path
#         self.emby_persons_path = emby_persons_path
#
#     async def listen_new(self):
#         await user.User(credential=).get_videos()


class Notify:
    """在下载整理完成时通知用户（走mr渠道） 只推送给第一个用户"""

    def __init__(self, video_info):
        self.video_info = video_info

    def send_message_by_templ(self):
        """发送模板消息"""
        raw_year = time.strftime("%Y", time.localtime(self.video_info["pubdate"]))
        title = f"{self.video_info['title']} ({raw_year}) 下载整理完成"
        pubtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.video_info["pubdate"]))
        desc = self.video_info['desc'][:100] + '...' if len(self.video_info['desc']) > 50 else self.video_info['desc']
        message = f"视频标题：{self.video_info['title']}\n" \
                  f"视频简介：{desc}\n" \
                  f"视频发布时间：{pubtime}\n" \
                  f"视频时长：{str(int(self.video_info['duration'] / 60))}分钟\n" \
                  f"视频标签：{self.video_info['tname']}\n"
        link_url = f"https://www.bilibili.com/video/{self.video_info['bvid']}"
        poster_url = self.video_info['pic']
        _LOGGER.info(f"开始发送模板消息")
        server.notify.send_message_by_tmpl(title=title, body=message,
                                           context={"link_url": link_url, "pic_url": poster_url}, to_uid=1)

    def send_sys_message(self):
        """发送系统消息"""
        _LOGGER.info("开始发送系统消息")
        server.notify.send_system_message(title="bilibili下载整理完成", to_uid=1,
                                          message="bilibili视频下载整理完成\n" + self.video_info['title'])

    def send_all_way(self):
        """发送所有通知方式"""
        self.send_message_by_templ()
        self.send_sys_message()


class DownloadFunc:
    """下载类 用于下载视频和封面"""

    def __init__(self, url, path):
        """
        :param url: 需要下载的url
        :param path: 保存的位置
        """
        self.url = url
        self.path = path

    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_fixed(10),
                    retry=tenacity.retry_if_result(lambda result: result is False))
    async def download_from_url(self):
        """使用异步下载"""
        try:
            _LOGGER.info(f"开始下载url：{self.url}，保存路径：{self.path}")
            async with httpx.AsyncClient(headers=HEADERS) as client:
                async with client.stream("GET", self.url) as response:
                    with open(self.path, "wb") as f:
                        async for data in response.aiter_bytes():
                            f.write(data)
        except Exception as e:
            _LOGGER.error(f"下载失败")
            tracebacklog = traceback.format_exc()
            _LOGGER.error(tracebacklog)
            return False
        else:
            _LOGGER.info(f"下载完成")
            return True


if __name__ == '__main__':
    start = time.time()
    list = ['BV1wT4y1k7Pw']
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    tasks = [BilibiliVideoProcess(i, emby_persons_path="E:\PycharmProjects\MovieRobotPlugins\BilibiliDownloadToEmby",
                                  if_get_character=True,
                                  media_path="E:\PycharmProjects\MovieRobotPlugins\BilibiliDownloadToEmby").process()
             for i in list]
    loop.run_until_complete(asyncio.wait(tasks))
    end = time.time()
    print('elapsed time = ' + str(end - start))
