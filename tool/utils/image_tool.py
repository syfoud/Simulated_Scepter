"""
全局图像资源导入工具
将图像目录下的所有图片一次性加载到内存中，避免重复读取
"""

import os

import cv2
import numpy as np
from PIL import Image

from tool.log import CUS_LOGGER

# 全局图像缓存字典，支持嵌套结构
_image_cache: dict = {}
# 存储图像目录路径
_image_directory: str = ""


def load_all_images_from_directory(directory_path: str = None) -> dict[str, bool]:
    """
    将指定目录下的所有图像加载到内存中

    Args:
        directory_path: 图像目录路径

    Returns:
        Dict[str, bool]: 每个图像文件的加载结果，True表示成功，False表示失败
    """
    global _image_cache

    # 如果没有指定路径，使用默认的图像目录
    if directory_path is None:
        from route import PATHS
        directory_path = PATHS["image"]

    # 保存目录路径供后续使用
    global _image_directory
    _image_directory = directory_path

    # 支持的图像扩展名
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}

    # 清空之前的缓存
    _image_cache.clear()

    # 递归构建嵌套字典结构
    def build_nested_dict(root_path):
        result = {}
        for item in os.listdir(root_path):
            item_path = os.path.join(root_path, item)
            if os.path.isdir(item_path):
                # 递归处理子文件夹
                sub_dict = build_nested_dict(item_path)
                if sub_dict:  # 只有当子文件夹有图像时才添加
                    result[item] = sub_dict
            elif os.path.isfile(item_path):
                # 处理文件
                if os.path.splitext(item)[1].lower() in image_extensions:
                    result[item] = item_path
        return result

    # 构建嵌套结构
    nested_structure = build_nested_dict(directory_path)
    _image_cache.clear()
    _image_cache.update(nested_structure)

    # 统计总文件数
    def count_files(structure):
        count = 0
        for key, value in structure.items():
            if isinstance(value, dict):
                count += count_files(value)
            else:
                count += 1
        return count

    total_files = count_files(_image_cache)
    CUS_LOGGER.info(f"发现 {total_files} 个记忆图像切片，正在载入缓冲区...")

    # 递归加载所有图像
    def load_images_recursive(structure, results_dict):
        success_count = 0
        for key, value in structure.items():
            if isinstance(value, dict):
                # 递归处理子文件夹
                sub_results = {}
                sub_success = load_images_recursive(value, sub_results)
                results_dict[key] = sub_results
                success_count += sub_success
            else:
                # 加载具体图像文件
                image_path = value
                try:
                    # 检查是否在gray_image文件夹中
                    is_gray_image = 'gray_image' in image_path.replace('\\', '/').split('/')

                    # 根据文件夹决定读取模式
                    if is_gray_image:
                        image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                    else:
                        image = cv2.imread(image_path, cv2.IMREAD_COLOR)
                    if image is None:
                        with Image.open(image_path) as pil_img:
                            image = np.array(pil_img)
                            if len(image.shape) == 3 and image.shape[2] == 4:
                                image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
                            # 如果是gray_image文件夹，转换为灰度
                            if is_gray_image and len(image.shape) == 3:
                                image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

                    if image is not None:
                        structure[key] = image  # 替换路径为图像数据
                        results_dict[key] = True
                        success_count += 1
                    else:
                        results_dict[key] = False
                        CUS_LOGGER.warning(f"无法加载图像记忆切片: {key}")
                except Exception as e:
                    results_dict[key] = False
                    CUS_LOGGER.error(f"加载图像记忆切片时出错 {key}: {str(e)}")
        return success_count

    results = {}
    success_count = load_images_recursive(_image_cache, results)

    CUS_LOGGER.info(f"图像记忆切片载入完成: {success_count}/{total_files} 成功")
    return results




def find_image_in_folder(folder_path: str, image_identifier: str, search_subfolders: bool = False) -> np.ndarray | None:
    """
    在指定文件夹的内存缓存中查找图像

    Args:
        folder_path: 相对于图像根目录的文件夹路径（如 'boss/' 或 'map/'）
        image_identifier: 图像文件名（可以带.jpg后缀也可以不带）
        search_subfolders: 是否递归搜索子文件夹，默认False

    Returns:
        np.ndarray: 图像数据，如果找不到返回None

    Examples:
        # >>> img = find_image_in_folder('boss/', 'run')
        # >>> img = find_image_in_folder('map/', 'ff1.jpg')
        # >>> img = find_image_in_folder('boss/', 'run', search_subfolders=True)
    """
    global _image_cache

    # 处理空路径情况
    if not folder_path or folder_path == './' or folder_path == '.':
        folder_path = ''
    # 确保非空路径以/结尾
    elif not folder_path.endswith('/'):
        folder_path = folder_path + '/'

    # 移除可能的扩展名用于标准化比较
    clean_identifier = os.path.splitext(image_identifier)[0]

    # 在指定文件夹中查找
    if folder_path:
        folder_parts = folder_path.strip('/').split('/')
        current_dict = _image_cache
        # 导航到指定文件夹
        for part in folder_parts:
            if part and part in current_dict:
                current_dict = current_dict[part]
            else:
                CUS_LOGGER.warning(f"指定的图像记忆切片文件夹不存在: {folder_path}")
                return None
    else:
        # 空路径，使用根目录
        current_dict = _image_cache

    # 在目标文件夹中查找图像
    if isinstance(current_dict, dict):
        if search_subfolders:
            # 递归搜索所有子文件夹
            def recursive_search(search_dict):
                for key, value in search_dict.items():
                    if isinstance(value, dict):
                        # 递归搜索子文件夹
                        result = recursive_search(value)
                        if result is not None:
                            return result
                    elif isinstance(value, np.ndarray):
                        # 检查图像匹配
                        key_without_ext = os.path.splitext(key)[0]
                        if key == image_identifier or key_without_ext == clean_identifier:
                            return value.copy()
                return None

            result = recursive_search(current_dict)
            if result is not None:
                return result
        else:
            # 只在当前文件夹中查找
            # 查找完全匹配（带.jpg）
            if image_identifier in current_dict:
                image_data = current_dict[image_identifier]
                if isinstance(image_data, np.ndarray):
                    return image_data.copy()

            # 查找不带后缀的匹配
            if clean_identifier in current_dict:
                image_data = current_dict[clean_identifier]
                if isinstance(image_data, np.ndarray):
                    return image_data.copy()

            # 查找部分匹配（文件名前缀）
            for key, value in current_dict.items():
                if isinstance(value, np.ndarray):  # 确保是图像数据
                    key_without_ext = os.path.splitext(key)[0]
                    if key_without_ext == clean_identifier:
                        return value.copy()

    warning_msg = f"在图像记忆切片文件夹 '{folder_path}'"
    if search_subfolders:
        warning_msg += "及其子文件夹"
    warning_msg += f"中未找到图像: {image_identifier}"
    CUS_LOGGER.warning(warning_msg)
    return None




def find_image_by_name(image_identifier: str) -> np.ndarray | None:
    """
    根据文件名（带或不带后缀）查找图像

    Args:
        image_identifier: 图像标识符，可以是带后缀的文件名('run.jpg')或不带后缀的名称('run')

    Returns:
        np.ndarray: 图像数据，如果找不到返回None
    """
    global _image_cache

    # 分离文件名和扩展名
    name_part, ext_part = os.path.splitext(image_identifier)
    has_extension = bool(ext_part)

    # 在整个缓存中递归搜索
    def search_image(structure, current_path=[]):
        for key, value in structure.items():
            if isinstance(value, dict):
                # 递归搜索子文件夹
                result = search_image(value, current_path + [key])
                if result is not None:
                    return result
            elif isinstance(value, np.ndarray):
                # 检查文件名匹配
                file_name, file_ext = os.path.splitext(key)
                if has_extension:
                    # 精确匹配带后缀的文件名
                    if key == image_identifier:
                        return value.copy()
                else:
                    # 不带后缀，匹配文件名部分
                    if file_name == name_part:
                        return value.copy()
        return None

    result = search_image(_image_cache)
    if result is None:
        # 缓存中未找到，尝试从磁盘加载
        CUS_LOGGER.warning(f"未在记忆切片缓存中找到 {image_identifier}，尝试从磁盘加载...")
        result = _load_image_from_disk(image_identifier)
        if result is None:
            CUS_LOGGER.error(f"磁盘中未找到图像记忆切片: {image_identifier}")

    return result


def _load_image_from_disk(image_identifier: str) -> np.ndarray | None:
    """
    从磁盘加载单个图像到缓存中

    Args:
        image_identifier: 图像标识符

    Returns:
        np.ndarray: 图像数据，如果加载失败返回None
    """
    global _image_cache, _image_directory

    if not _image_directory:
        CUS_LOGGER.error("记忆切片查询失败，图像目录未初始化")
        return None

    # 分离文件名和扩展名
    name_part, ext_part = os.path.splitext(image_identifier)
    has_extension = bool(ext_part)

    # 支持的图像扩展名
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}

    # 递归搜索磁盘上的图像文件
    def search_file_in_directory(root_path, target_name, target_ext, has_ext):
        for item in os.listdir(root_path):
            item_path = os.path.join(root_path, item)
            if os.path.isdir(item_path):
                # 递归搜索子目录
                result = search_file_in_directory(item_path, target_name, target_ext, has_ext)
                if result:
                    return result
            elif os.path.isfile(item_path):
                file_name, file_ext = os.path.splitext(item)
                # 检查是否匹配
                if has_ext:
                    # 精确匹配带后缀的文件名
                    if item == target_name:
                        return item_path
                else:
                    # 不带后缀，匹配文件名部分
                    if file_name == target_name and file_ext.lower() in image_extensions:
                        return item_path
        return None

    # 在磁盘中查找文件
    file_path = search_file_in_directory(_image_directory, image_identifier, ext_part, has_extension)

    if file_path:
        try:
            # 检查是否在gray_image文件夹中
            is_gray_image = 'gray_image' in file_path.replace('\\', '/').split('/')

            # 根据文件夹决定读取模式
            if is_gray_image:
                image = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
                CUS_LOGGER.debug(f"磁盘加载时使用灰度模式: {image_identifier}")
            else:
                image = cv2.imread(file_path, cv2.IMREAD_COLOR)

            if image is None:
                with Image.open(file_path) as pil_img:
                    image = np.array(pil_img)
                    if len(image.shape) == 3 and image.shape[2] == 4:
                        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
                    # 如果是gray_image文件夹，转换为灰度
                    if is_gray_image and len(image.shape) == 3:
                        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

            if image is not None:
                # 将图像添加到缓存中
                relative_path = os.path.relpath(file_path, _image_directory)
                path_parts = relative_path.split(os.sep)

                # 在缓存中创建对应的嵌套结构
                current_dict = _image_cache
                for part in path_parts[:-1]:  # 除了最后一个（文件名）
                    if part not in current_dict:
                        current_dict[part] = {}
                    current_dict = current_dict[part]

                # 添加图像数据
                current_dict[path_parts[-1]] = image
                CUS_LOGGER.info(f"成功从磁盘加载图像记忆切片: {image_identifier} -> {relative_path}")
                return image.copy()
            else:
                CUS_LOGGER.error(f"无法加载图像记忆切片: {file_path}")
        except Exception as e:
            CUS_LOGGER.error(f"加载图像记忆切片时出错 {file_path}: {str(e)}")

    return None





def clear_image_cache():
    """清空图像缓存（但保留目录路径）"""
    global _image_cache
    cache_size = len(_image_cache)
    _image_cache.clear()
    CUS_LOGGER.info(f"已焚化图像记忆切片缓存，释放了 {cache_size} 个图像记忆切片")


def get_cache_size() -> int:
    """获取缓存中的图像数量"""
    global _image_cache
    return len(_image_cache)


def print_cache_info():
    """打印缓存信息"""
    global _image_cache

    def count_images(structure):
        count = 0
        memory = 0
        for key, value in structure.items():
            if isinstance(value, dict):
                sub_count, sub_memory = count_images(value)
                count += sub_count
                memory += sub_memory
            elif isinstance(value, np.ndarray):
                count += 1
                memory += value.nbytes
        return count, memory

    def print_structure(structure, indent=0):
        for key, value in structure.items():
            if isinstance(value, dict):
                CUS_LOGGER.info("  " * indent + f"📁 {key}/")
                print_structure(value, indent + 1)
            elif isinstance(value, np.ndarray):
                CUS_LOGGER.info("  " * indent + f"📄 {key} ({value.shape})")
            else:
                CUS_LOGGER.info("  " * indent + f"🔗 {key} -> {value}")

    count, memory = count_images(_image_cache)
    CUS_LOGGER.info(f"当前缓存图像数量: {count}")
    CUS_LOGGER.info(f"缓存总内存占用: {memory / (1024*1024):.2f} MB")

    if _image_cache:
        CUS_LOGGER.info("缓存结构:")
        print_structure(_image_cache)




if __name__ == "__main__":
    # 测试代码
    CUS_LOGGER.info("开始测试全局图像缓存功能")

    # 加载所有图像
    results = load_all_images_from_directory()

    # 打印缓存信息
    print_cache_info()
