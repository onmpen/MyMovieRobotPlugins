import logging
import os

_LOGGER = logging.getLogger(__name__)
dependent_modules = {'bilibili_api': 'bilibili-api-python', 'zxing': 'zxing', 'apscheduler': 'apscheduler',
                     'PIL': 'pillow'}
source = "https://pypi.tuna.tsinghua.edu.cn/simple"


def install():
    for module in dependent_modules:
        try:
            __import__(module)
        except ImportError:
            _LOGGER.warning(f"没找到 {module} 模块，正在尝试安装")
            os.system(f"pip install {dependent_modules[module]} -i {source}")
            _LOGGER.info(f"安装 {module} 模块成功")


install()

from .cron_tasks import *
from .mr_commands import *
from .events import *
