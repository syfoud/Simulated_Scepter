
import cv2 as cv
import numpy as np

from tool.log import CUS_LOGGER
from tool.onnxocr.onnx_paddleocr import ONNXPaddleOcr
from tool.public_ocr import box_contain, filter_non_white, merge, sort_text

# mode: bless1 bless2 strange

def is_edit_distance_at_most_one(str1, str2, ch):
    length = len(str1)
    #两个字符串之间的不同的位数
    diff_count = sum(1 for i in range(length) if str1[i] != str2[i])
    if diff_count <= 1:
        return 1
    i = 0
    j = 0
    diff_count = 0
    str2 += ch
    while i < length and j < length + 1:
        if str1[i] != str2[j]:
            diff_count += 1
            j += 1
        else:
            i += 1
            j += 1

    return diff_count <= 1


# 全局唯一的 OCR 包装器实例
_global_my_ts_instance = None

def get_global_my_ts(father=None):
    """
    获取全局唯一的 My_TS 实例
    确保整个程序生命周期内只创建一个 OCR 实例，避免内存泄露
    """
    global _global_my_ts_instance
    if _global_my_ts_instance is None:
        CUS_LOGGER.info("欢呼「毁灭」的英雄，初次点燃生命的微光。原本晦暗的前路仿佛也变得有迹可循。")
        _global_my_ts_instance = object.__new__(My_TS)
        _global_my_ts_instance.lang = 'ch'
        _global_my_ts_instance.father = father
        _global_my_ts_instance.forward_img = None
        _global_my_ts_instance.res = []
        _global_my_ts_instance.nothing = 1
        _global_my_ts_instance.text = ''
        _global_my_ts_instance._ts = None
    else:
        _global_my_ts_instance.father = father
    return _global_my_ts_instance

class My_TS:
    # 类变量，用于共享底层 OCR 引擎
    _ts_shared = None

    def __init__(self, lang='ch', father=None):
        self.lang = lang
        self.father = father
        self.forward_img = None
        self.res = []
        self.nothing = 1
        self.text = ''
        self._ts = None

    @property
    def ts(self):
        """懒加载 OCR 实例"""
        if self._ts is None:
            if My_TS._ts_shared is None:
                CUS_LOGGER.info("焚身作薪……为来世破晓…引火吧。")
                CUS_LOGGER.info("其时已至……再度…开启一切……")
                My_TS._ts_shared = ONNXPaddleOcr(use_angle_cls=False, cpu=False)
            self._ts = My_TS._ts_shared
        return self._ts

    def similar(self, text, img=None):
        """
        模糊匹配文本
        """
        if img is not None:
            self.ocr_one_row_and_save(img)
        self.text = self.text.strip()
        if text.strip() in ['胜军','脊刺','佩拉']:
            #输入文本为上述且在self.text中则True
            return text.strip() in self.text
        length = len(text)
        res = 0
        stext = self.text+' '
        for i in range(len(stext)-length):
            #滑动窗口检测所有长度为length的子串
            res |= is_edit_distance_at_most_one(text,stext[i:i+length],stext[i+length])
        # CUS_LOGGER.debug(f"{self.text}与{ text}是否相似：{res}")
        return res

    def ocr_one_row(self, img, box=None):
        if box is None:
            return self.ts.text_recognizer([img])[0][0]
        else:
            # log.debug(f"ocr结果{self.ts.text_recognizer([img[box[2]:box[3], box[0]:box[1]]])}")
            return self.ts.text_recognizer([img[box[2]:box[3], box[0]:box[1]]])[0][0]

    def ocr_one_row_and_save(self, img):
        """
        对图像进行OCR识别，并将结果转换为小写
        """
        try:
            self.text=self.ocr_one_row(img).lower()
        except Exception:
            self.text=''
    def similar_list(self, text_list, img=None):
        """
        列表逐个模糊匹配，匹配到则返回对应的
        """
        if img is not None:
            self.ocr_one_row_and_save(img)
        for t in text_list:
            if self.similar(t):
                return t
        return None

    def split_and_find(self,key_list,img,mode=None,bless_skip=1,black_list=[]):
        white=[255,255,255]
        yellow=[126,162,180]
        binary_image = np.zeros_like(img[:, :, 0])
        enhance_image = np.zeros_like(img)
        if mode=='strange':
            binary_image[np.sum((img - yellow) ** 2, axis=-1) <= 512]=255
            enhance_image[np.sum((img - yellow) ** 2, axis=-1) <= 3200]=[255,255,255]
        else:
            binary_image[np.sum((img - white) ** 2, axis=-1) <= 1600]=255
            enhance_image[np.sum((img - white) ** 2, axis=-1) <= 3200]=[255,255,255]
        if mode=='bless':
            kerneld = np.zeros((7,3),np.uint8) + 1
            kernele = np.zeros((1,39),np.uint8) + 1
            kernele2 = np.zeros((7,1),np.uint8) + 1
            binary_image = cv.dilate(binary_image,kerneld,iterations=2)
            binary_image = cv.erode(binary_image,kernele,iterations=5)
            binary_image = cv.erode(binary_image,kernele2,iterations=2)
            enhance_image = img
        else:
            kernel = np.zeros((5,9),np.uint8) + 1
            for i in range(2):
                binary_image = cv.dilate(binary_image,kernel,iterations=3)
                binary_image = cv.erode(binary_image,kernel,iterations=2)
        contours, _ = cv.findContours(binary_image, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        prior = len(key_list)
        rcx,rcy,find,black=-1,-1,0,0
        res=''
        text_res='无'
        for c,contour in enumerate(contours):
            x, y, w, h = cv.boundingRect(contour)
            if h==binary_image.shape[0] or w<55:
                continue
            roi = enhance_image[y:y+h, x:x+w]
            cx = x + w // 2
            cy = y + h // 2
            self.ocr_one_row_and_save(roi)
            if len(self.text.strip())<=1:
                continue
            if find == 0:
                rcx,rcy,find,text_res = cx,cy,1,self.text+';'
            res+='|'+self.text
            if (self.similar('回归不等式') and bless_skip) or self.similar_list(black_list) is not None:
                black = 1
                res+='x'
                continue
            if find == 1:
                rcx,rcy,text_res=cx,cy,self.text+'?'
            for i,text in enumerate(key_list):
                if i==prior:
                    break
                if self.similar(text):
                    rcx,rcy,find=cx,cy,2
                    text_res=text+'!'
                    prior=i
        CUS_LOGGER.debug(f'识别结果：{res}+ 识别到：{text_res}')
        if black and find==1:
            find=3
        return (rcx-img.shape[1]//2,rcy-img.shape[0]//2),find+black
    def split_strange(self,img):
        yellow=[126,162,180]
        binary_image = np.zeros_like(img[:, :, 0])
        enhance_image = np.zeros_like(img)
        binary_image[np.sum((img - yellow) ** 2, axis=-1) <= 512]=255
        enhance_image[np.sum((img - yellow) ** 2, axis=-1) <= 3200]=[255,255,255]
        kernel = np.zeros((5,9),np.uint8) + 1
        for i in range(2):
            binary_image = cv.dilate(binary_image,kernel,iterations=3)
            binary_image = cv.erode(binary_image,kernel,iterations=2)
        contours, _ = cv.findContours(binary_image, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        res=[]
        point_list=[]
        for c,contour in enumerate(contours):
            x, y, w, h = cv.boundingRect(contour)
            if h==binary_image.shape[0] or w<55:
                continue
            roi = enhance_image[y:y+h, x:x+w]
            cx = x + w // 2
            cy = y + h // 2
            self.ocr_one_row_and_save(roi)
            if len(self.text.strip())<=1:
                continue
            point_list.append((cx-img.shape[1]//2,cy-img.shape[0]//2))
            res.append(self.text)
        CUS_LOGGER.debug(f'识别奇物结果：{res}')
        return point_list,res
    def find_text(self, img, text,find_all=False):
        self.nothing = 1
        results = self.ts.ocr(img)
        # log.debug(f"识别到文本：{results}")
        find_all_return = None
        for res in results:
            res = {'raw_text': res[1][0], 'box': np.array(res[0]), 'score': res[1][1]}
            self.text = res['raw_text']
            if len(self.text.strip())>1 and 'UID' not in self.text:
                self.nothing = 0
            # 处理text可能是列表的情况
            found = False
            matched_text = text
            if isinstance(text, list):
                for t in text:
                    if t in self.text:
                        found = True
                        matched_text = t
                        break
            else:
                found = text in self.text

            if found:
                CUS_LOGGER.debug(f"识别到文本：{matched_text}匹配文本：{self.text},位置：{[int(res['box'][0][0]), int(res['box'][1][0]), int(res['box'][0][1]), int(res['box'][2][1])]}")
                if not find_all:
                    return res['box']
                else:
                    find_all_return = res['box']
                    continue
        if find_all_return is not None:
            return find_all_return
        return None
    def forward(self, img):
        """
        识别传入图像的文本并保存在self.res中
        """
        self.nothing = 1
        if self.forward_img is not None and self.forward_img.shape == img.shape and np.sum(np.abs(self.forward_img-img))<1e-6:
            return
        self.forward_img = img
        self.res = []
        ocr_res = self.ts.ocr(img)
        for res in ocr_res:
            res = {'raw_text': res[1][0], 'box': np.array(res[0]), 'score': res[1][1]}
            res['box'] = [int(np.min(res['box'][:,0])),int(np.max(res['box'][:,0])),int(np.min(res['box'][:,1])),int(np.max(res['box'][:,1]))]
            self.res.append(res)
        if len(self.res):
            self.nothing = 0
        self.res = merge(self.res)
    def find_with_box(self, box=None, redundancy=10, forward=0, mode=0,re_screen=False):
        """
        在指定文本框内
        Args:
            :param box: 一个指定的范围框[左上x,右下x,左上y,右下y]
            :param redundancy: 误差范围
            :param forward:
            :param mode: 图像处理保留的模式

        return:
            指定区域提取的排序文字
        """
        if re_screen and forward and box is not None:
            self.forward(filter_non_white(self.father.get_screen()[box[2]:box[3], box[0]:box[1]], mode=mode))
        elif forward and box is not None:
            self.forward(filter_non_white(self.father.screen.copy()[box[2]:box[3], box[0]:box[1]], mode=mode))

        ans = []
        for res in self.res:
            if box is None:
                CUS_LOGGER.debug(f"文本：{res['raw_text']}, 坐标：{res['box']}")
            elif forward == 0:
                if box_contain(box, res['box'], redundancy=redundancy):
                    ans.append(res)
            else:
                #叠加指定偏移
                res['box'] = [box[0]+res['box'][0], box[0]+res['box'][1], box[2]+res['box'][2], box[2]+res['box'][3]]
                ans.append(res)
        return sort_text(ans)

    @classmethod
    def cleanup(cls):
        """
        清理共享 OCR 资源
        """
        global _global_my_ts_instance
        if cls._ts_shared is not None:
            CUS_LOGGER.info("这一次，逐火的终点………也并无不同。天边升起的，是世人前所未见的，极为纯粹的金色，纯粹到足以烧尽一切……这便是世界的终结，也是下一个世界的起点……")
            cls._ts_shared = None
        # 重置全局实例引用，允许下次重新创建
        _global_my_ts_instance = None
