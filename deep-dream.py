#!/usr/bin/python
from functools import partial
from PIL import Image as image
import numpy as np 
import tensorflow as tf 
import matplotlib.pyplot as plt 
import urllib.request
import os
import zipfile

def main():
   #Download Google's already trained neural network via the TensorFlow API
   url = 'http://storage.googleapis.com/download.tensorflow.org/models/inception5h.zip'
   data_dir = '../data/'
   model_name = os.path.split(url)[-1]
   local_zip_file = os.path.join(data_dir, model_name)
   if not os.path.exists(local_zip_file):
      #Download the file
      model_url = urllib.request.urlopen(url)
      with open(local_zip_file, 'wb') as output:
         output.write(model_url.read())
      #Now extract the file using zipfile
      with zipfile.ZipFile(local_zip_file, 'r') as zip_ref:
         zip_ref.extractall(data_dir)

      #First start off with a grey image with some noise
      img_noise = np.random.uniform(size = (224, 224, 3)) + 100.0
      #The TensorFlow graph when logging into the dashboard
      model_fn = 'tensorflow_inception_graph.pb'

      #Create TensorFlow session and load the model
      graph = tf.Graph()
      sess = tf.InteractiveSession(graph = graph)
      with tf.gfile.FastGFile(os.path.join(data_dir, model_fn), 'rb') as f:
         graph_def = tf.GraphDef()
         graph_def.ParseFromString(f.read())

      #Define the input tensor
      t_input = tf.placeholder(np.float32, name = 'input') 
      imagenet_mean = 117.0
      t_preprocessed = tf.expand_dims(t_input-imagenet_mean, 0);
      tf.import_graph_def(graph_def, {'input':t_preprocessed})
      
      layers = [op.name for op in graph.get_operations() if op.type == 'Conv2D' and 'import/' in op.name]
      feature_nums = [int(graph.get_tensor_by_name(name + ':0').get_shape()[-1]) for name in layers]

      print('Number of layers', len(layers))
      print('Total number of feature channels:', sum(feature_nums))

      #The following are helper functions, used for formatting

      #Function for TF Graph visualization
      def strip_consts(graph_def, max_const_size = 32):
         #Strip large constant values from graph_def
         strip_def = tf.GraphDef()
         for n0 in graph_def.node:
            n = strip_def.node.add()
            n.MergeFrom(n0)
            if n.op == 'Const':
               tensor = n.attr['value'].tensor
               size = len(tensor.tensor_content)
               if max_const_size < size:
                  tensor.tensor_content = "<stripped %d bytes"%size
         return strip_def

         def rename_nodes(graph_def, rename_func):
            res_def = tf.GraphDef()
            for n0 in graph_def.node:
               n = res_def.node.add()
               n.MergeFrom(n0)
               n.name = rename_func(n.name)
               for i, s in enumerate(n.input):
                  n.input[i] = rename_func(s) if s[0] != '^' else '^' + rename_func(s[1:])
            return res_def
             
         def showarray(a):
            a = np.uint8(np.clip(a, 0, 1) * 255)
            plt.imshow(a)
            plt.show()

         def visstd(a, s = 0.1):
            #Normalize the image range for visualization
            return (a - a.mean()) / max(a.std(), 1e-4) * s + 0.5
            
         #Function for getting layer ouput tensor
         def T(layer):
            return graph.get_tensor_by_name("import/%s:0"%layer)

         def render_naive(t_obj, img0 = img_noise, iter_n = 20, step = 1.0):
            #Define the optimization of objective
            t_score = tf.reduce_mean(t_obj)

            #Automatic differentiation
            t_grad = tf.gradients(t_score, t_input)[0]

            img = img0.copy()
            for _ in range(iter_n):
               g, _ = sess.run([t_grad, t_score], {t_input:img})

               #Normalize the gradient, for the step size to work
               #For different layers and networks
               g /= g.std() + 1e-8
               img += g * step
            showarray(visstd(img))

         #Function for transforming TF-graph to generate function into a regular function
         def tffunc(*argtypes):
            placeholders = list(map(tf.placeholder, argtypes))
            def wrap(f):
               out = f(*placeholders)
               def wrapper(*args, **kw):
                  return out.eval(dict(zip(placeholders, args)), session = kw.get('session'))
               return wrapper
            return wrap 

         #Function used along with above function
         def resize(img, size):
            img = tf.expand_dims(img, 0)
            return tf.image.resize_bilinear(img, size)[0, :, :, :]
         resize = tffunc(np.float32, np.int32)(resize)

         """Function computes the value of tensor t_grad over the image in a tiled way
         Random shifts are applied to image to blur tile boundaries over multiple iterations"""
         def calc_grad_tiled(img, t_grad, tile_size = 512):
            sz = tile_size
            h, w = img.shape[:2]
            sx, sy = np.random.randint(sz, size = 2)
            img_shift = np.roll(np.roll(img, sx, 1), sy, 0)
            grad = np.zeros_like(img)
            for y in range(0, max(h - sz // 2, sz), sz):
               for x in range(0, max(w - sz // 2, sz), sz):
                  sub = img_shift[y:y + sz, x:x + sz]
                  g = sess.run(t_grad, {t_input:sub})
                  grad[y:y + sz, x:x + sz] = g
         return np.roll(np.roll(grad, -sx, 1), -sy, 0)

         def render_deepdream(t_obj, img0 = img_noise, iter_n = 10, step = 1.5, octave_n = 4, octave_scale = 1.4):
            #Define the optimization of objective
            t_score = tf.reduce_mean(t_obj)

            #Automatic differentiation once again
            t_grad = tf.gradients(t_score, t_input)[0]

            #Split the image into a number of octaves
            img = img0
            octaves = []
            for _ in range(octave_n - 1):
               hw = img.shape[:2]
               lo = resize(img, np.int32(np.float32(hw) / octave_scale))
               hi = img - resize(lo, hw)
               img = lo
               octaves.append(hi)

            #Generate details octave by octave
            for octave in range(octave_n):
               if octave > 0:
                  hi = octaves[-octave]
                  img = resize(img, hi.shape[:2]) + hi
               for _ in range(iter_n):
                  g = calc_grad_tiled(img, t_grad)
                  img += g * (step / (np.abs(g).mean() + 1e-7))

               #Output the deep dream image via matplotlib!!!
               showarray(img / 255.0)

         #Pick a layer to enhance the image with
         layer = 'mixed4d_3x3_bottleneck_pre_relu'
         
         #Pick a feature channel to visualize
         channel = 139

         """Open the image 
         Here the image is 'pilatus800.jpg' - Feel free to change
         """
         img0 = image.open('pilatus800.jpg')
         img0 = np.float32(img0)

         #Apply gradient ascent to the layer variable as defined above!
         render_deepdream(tf.square(T('mixed4c')), img0)

if __name__ == '__main__':
      main()