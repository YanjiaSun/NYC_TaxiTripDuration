#!/usr/bin/python
# -*- coding: utf-8 -*-
""" Utils

.. See https://github.com/PaulEmmanuelSotir/NYC_TaxiTripDuration
"""
import tensorflow as tf

__all__ = ['tf_config', 'visualize_weights']

def tf_config(allow_growth=True, **kwargs):
    config = tf.ConfigProto(**kwargs)
    config.gpu_options.allow_growth = allow_growth
    return config

def visualize_weights(weights, name, max_images=3):
    image = tf.reshape(weights, [1, weights.shape[0].value,  weights.shape[1].value, 1])
    tf.summary.image(name, image, max_outputs=max_images)