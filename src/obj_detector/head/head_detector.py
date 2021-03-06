#-*- coding:utf-8 -*-

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function

import os
import torch
import argparse
import torch.nn as nn
import torch.utils.data as data
import torch.backends.cudnn as cudnn
import torchvision.transforms as transforms
from torch.autograd import Variable

import cv2
import time
import numpy as np
from tqdm import tqdm
from matplotlib import pyplot as plt

from head_detection import Detect
from config_head import cfg
# from s3fd import build_s3fd
from vgg16 import S3FD
from priorbox import PriorBox
from box_utils import nms_py

def parms():
    parser = argparse.ArgumentParser(description='s3df demo')
    parser.add_argument('--save_dir', type=str, default='tmp/',
                        help='Directory for detect result')
    parser.add_argument('--headmodelpath', type=str,
                        default='weights/s3fd.pth', help='trained model')
    parser.add_argument('--conf_thresh', default=0.65, type=float,
                        help='Final confidence threshold')
    parser.add_argument('--ctx', default=True, type=bool,
                        help='gpu run')
    parser.add_argument('--img_dir', type=str, default='tmp/',
                        help='Directory for images')
    parser.add_argument('--file_in', type=str, default='tmp.txt',
                        help='image namesf')
    return parser.parse_args()


class HeadDetect(object):
    def __init__(self,args):
        if args.ctx and torch.cuda.is_available():
            self.use_cuda = True
        else:
            self.use_cuda = False
        if self.use_cuda:
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
        else:
            torch.set_default_tensor_type('torch.FloatTensor')
        self.loadmodel(args.headmodelpath)
        self.threshold = args.conf_thresh
        self.img_dir = args.img_dir
        
        self.detect = Detect(cfg)
        self.Prior = PriorBox(cfg)
        with torch.no_grad():
            self.priors =  self.Prior.forward()

    def loadmodel(self,modelpath):
        if self.use_cuda:
            device = 'cuda'
        else:
            device = 'cpu'
        # self.net = build_s3fd('test', cfg.NUM_CLASSES)
        self.net = S3FD(cfg.NUM_CLASSES)
        self.net.load_state_dict(torch.load(modelpath,map_location=device))
        self.net.eval()
        # print(self.net)
        if self.use_cuda:
            self.net.cuda()
            cudnn.benckmark = True
    def propress(self,img):
        rgb_mean = np.array([123.,117.,104.])[np.newaxis, np.newaxis,:].astype('float32')
        img = cv2.resize(img,(cfg.resize_width,cfg.resize_height))
        img = cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
        img = img.astype('float32')
        img -= rgb_mean
        #img = img[:,:,::-1]
        img = np.transpose(img,(2,0,1))
        return img
    def xyxy2xywh(self,bbox_score):
        bboxes = bbox_score[0]
        bbox = bboxes[0] 
        score = bboxes[1]
        bbox[:,2] = bbox[:,2] -bbox[:,0] 
        bbox[:,3] = bbox[:,3] -bbox[:,1]  
        bbox_out=[]
        scores = []
        for j in range(bbox.shape[0]):
            dets = bbox[j] 
            sc = score[j]
            min_re = min(dets[2],dets[3])
            if min_re < 16:
                thresh = 0.2
            else:
                thresh = 0.8
            if sc >= thresh:
                bbox_out.append(dets)
                scores.append(sc)
        return np.array(bbox_out),np.array(scores)
    def nms_filter(self,bboxes,scale):
        boxes = bboxes[0][0] * scale
        scores = bboxes[0][1]
        ids, count = nms_py(boxes, scores, 0.3,1000)
        boxes = boxes[ids[:count]]
        scores = scores[ids[:count]]
        return [[boxes,scores]]
    def inference_img(self,imgorg):
        t1 = time.time()
        imgh,imgw = imgorg.shape[:2]
        scale = np.array([imgw,imgh,imgw,imgh])
        scale = np.expand_dims(scale,0)
        img = self.propress(imgorg.copy())
        bt_img = Variable(torch.from_numpy(img).unsqueeze(0))
        if self.use_cuda:
            bt_img = bt_img.cuda()
        output = self.net(bt_img)
        t2 = time.time()
        with torch.no_grad():
            bboxes = self.detect(output[0],output[1],self.priors)
        t3 = time.time()
        bboxes = self.nms_filter(bboxes,scale)
        print('consuming:',t2-t1,t3-t2)
        #showimg = self.label_show(bboxes,imgorg)
        bbox = []
        score = []
        if len(bboxes)>0:
            bbox,score = self.xyxy2xywh(bboxes)
        # showimg = self.label_show(bbox,score,imgorg)
        return bbox,score
        # return showimg,bbox
    def label_show(self,rectangles,scores,img):
        # imgh,imgw,_ = img.shape
        # scale = np.array([imgw,imgh,imgw,imgh])
        for j in range(rectangles.shape[0]):
            dets = rectangles[j]
            score = scores[j]
            x1,y1 = dets[:2]
            x2,y2 = dets[:2] +dets[2:]
            cv2.rectangle(img,(int(x1),int(y1)),(int(x2),int(y2)),(0,0,255),2)
            txt = "{:.3f}".format(score)
            point = (int(x1),int(y1-5))
            cv2.putText(img,txt,point,cv2.FONT_HERSHEY_COMPLEX,0.5,(0,255,0),1)
        return img

    def detectheads(self,imgpath):
        if os.path.isdir(imgpath):
            cnts = os.listdir(imgpath)
            for tmp in cnts:
                tmppath = os.path.join(imgpath,tmp.strip())
                img = cv2.imread(tmppath)
                if img is None:
                    continue
                showimg,_ = self.inference_img(img)
                cv2.imshow('demo',showimg)
                cv2.waitKey(0)
        elif os.path.isfile(imgpath) and imgpath.endswith('txt'):
            # if not os.path.exists(self.save_dir):
            #     os.makedirs(self.save_dir)
            f_r = open(imgpath,'r')
            file_cnts = f_r.readlines()
            for j in tqdm(range(len(file_cnts))):
                tmp_file = file_cnts[j].strip()
                if len(tmp_file.split(','))>0:
                    tmp_file = tmp_file.split(',')[0]
                if not tmp_file.endswith('jpg'):
                    tmp_file = tmp_file +'.jpeg'
                tmp_path = os.path.join(self.img_dir,tmp_file) 
                if not os.path.exists(tmp_path):
                    print(tmp_path)
                    continue
                img = cv2.imread(tmp_path) 
                if img is None:
                    print('None',tmp)
                    continue
                frame,_ = self.inference_img(img)                
                cv2.imshow('result',frame)
                #savepath = os.path.join(self.save_dir,save_name)
                #cv2.imwrite('test.jpg',frame)
                cv2.waitKey(0) 
        elif os.path.isfile(imgpath) and imgpath.endswith(('.mp4','.avi')) :
            cap = cv2.VideoCapture(imgpath)
            if not cap.isOpened():
                print("failed open camera")
                return 0
            else: 
                while cap.isOpened():
                    _,img = cap.read()
                    frame,_ = self.inference_img(img)
                    cv2.imshow('result',frame)
                    q=cv2.waitKey(10) & 0xFF
                    if q == 27 or q ==ord('q'):
                        break
            cap.release()
            cv2.destroyAllWindows()
        elif os.path.isfile(imgpath):
            img = cv2.imread(imgpath)
            if img is not None:
                # grab next frame
                # update FPS counter
                frame,odm_maps = self.inference_img(img)
                # hotmaps = self.get_hotmaps(odm_maps)
                # self.display_hotmap(hotmaps)
                # keybindings for display
                cv2.imshow('result',frame)
                #cv2.imwrite('test30.jpg',frame)
                key = cv2.waitKey(0) 
        else:
            print('please input the right img-path')

if __name__ == '__main__':
    args = parms()
    detector = HeadDetect(args)
    imgpath = args.file_in
    detector.detectheads(imgpath)