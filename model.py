#!/usr/bin/env python
# -*- coding: utf-8 -*-

from tensorflow.keras.layers import *
from tensorflow.keras.models import Model
from tensorflow.python.keras.backend import tile
from tensorflow.python.keras.models import load_model as _load_model
from tensorflow.keras.applications import inception_resnet_v2
import resnet50
import densenet

from metrics import weighted_mean_iou, weighted_mean_score, weighted_bce_dice_loss, weighted_binary_crossentropy, \
    l2_loss, weighted_lovasz_hinge, weighted_lovasz_dice_loss, weighted_lovasz_hinge_inversed, \
    weighted_lovasz_hinge_double
from util import get_metrics


def conv_block_simple(input, filters, prefix, strides=(1, 1)):
    conv = Conv2D(filters, (3, 3), padding="same", kernel_initializer="he_normal", strides=strides, name=prefix + "_conv")(input)
    conv = BatchNormalization(name=prefix + "_bn")(conv)
    conv = Activation('relu', name=prefix + "_activation")(conv)
    return conv


def get_unet_resnet50(input_shape):
    inputs = Input(shape=input_shape)
    base_model = resnet50.ResNet50(input_shape=input_shape, input_tensor=inputs, include_top=False, weights='imagenet')

    for i, layer in enumerate(base_model.layers):
        layer.trainable = True

    conv1 = base_model.get_layer("activation").output
    conv2 = base_model.get_layer("activation_9").output
    conv3 = base_model.get_layer("activation_21").output
    conv4 = base_model.get_layer("activation_39").output
    conv5 = base_model.get_layer("activation_48").output

    up6 = concatenate([UpSampling2D()(conv5), conv4], axis=-1)
    conv6 = conv_block_simple(up6, 256, "conv6_1")
    conv6 = conv_block_simple(conv6, 256, "conv6_2")

    up7 = concatenate([UpSampling2D()(conv6), conv3], axis=-1)
    conv7 = conv_block_simple(up7, 192, "conv7_1")
    conv7 = conv_block_simple(conv7, 192, "conv7_2")

    up8 = concatenate([UpSampling2D()(conv7), conv2], axis=-1)
    conv8 = conv_block_simple(up8, 128, "conv8_1")
    conv8 = conv_block_simple(conv8, 128, "conv8_2")

    up9 = concatenate([UpSampling2D()(conv8), conv1], axis=-1)
    conv9 = conv_block_simple(up9, 64, "conv9_1")
    conv9 = conv_block_simple(conv9, 64, "conv9_2")

    up10 = concatenate([UpSampling2D()(conv9), base_model.input], axis=-1)
    conv10 = conv_block_simple(up10, 32, "conv10_1")
    conv10 = conv_block_simple(conv10, 32, "conv10_2")

    return inputs, conv10


def get_unet_densenet121(input_shape):
    inputs = Input(shape=input_shape)
    base_model = densenet.DenseNet121(
        input_shape=input_shape, input_tensor=inputs, include_top=False, weights='imagenet')

    for i, layer in enumerate(base_model.layers):
        layer.trainable = True

    conv1 = base_model.get_layer("conv1/relu").output
    conv2 = base_model.get_layer("pool2_conv").output
    conv3 = base_model.get_layer("pool3_conv").output
    conv4 = base_model.get_layer("pool4_conv").output
    conv5 = base_model.get_layer("bn").output

    up6 = concatenate([UpSampling2D()(conv5), conv4], axis=-1)
    conv6 = conv_block_simple(up6, 256, "conv6_1")
    conv6 = conv_block_simple(conv6, 256, "conv6_2")

    up7 = concatenate([UpSampling2D()(conv6), conv3], axis=-1)
    conv7 = conv_block_simple(up7, 192, "conv7_1")
    conv7 = conv_block_simple(conv7, 192, "conv7_2")

    up8 = concatenate([UpSampling2D()(conv7), conv2], axis=-1)
    conv8 = conv_block_simple(up8, 128, "conv8_1")
    conv8 = conv_block_simple(conv8, 128, "conv8_2")

    up9 = concatenate([UpSampling2D()(conv8), conv1], axis=-1)
    conv9 = conv_block_simple(up9, 64, "conv9_1")
    conv9 = conv_block_simple(conv9, 64, "conv9_2")

    up10 = concatenate([UpSampling2D()(conv9), base_model.input], axis=-1)
    conv10 = conv_block_simple(up10, 32, "conv10_1")
    conv10 = conv_block_simple(conv10, 32, "conv10_2")

    return inputs, conv10

def build_model_pretrained(height, width, channels, encoder='resnet50',
                           spatial_dropout=None):
    if encoder == 'resnet50':
        inputs, outputs = get_unet_resnet50([height, width, channels])
    elif encoder == 'densenet121':
        inputs, outputs = get_unet_densenet121([height, width, channels])
    else:
        raise ValueError('encoder {} is not supported'.format(encoder))

    if spatial_dropout is not None:
        outputs = SpatialDropout2D(spatial_dropout)(outputs)
    outputs = Conv2D(1, (1, 1), name='prediction')(outputs)
    model = Model(inputs=[inputs], outputs=[outputs])
    return model


def build_model_ref(
        height, width, channels, out_ch=1, start_ch=16, depth=5, inc_rate=2,
        activation='relu', drop_out=0.5, batch_norm=True, maxpool=True, upconv=True, residual=False):
    """Copy from https://www.kaggle.com/dingli/seismic-data-analysis-with-u-net"""

    def conv_block(m, dim, acti, bn, res, do=0):
        n = Conv2D(dim, 3, activation=acti, padding='same')(m)
        n = BatchNormalization()(n) if bn else n
        n = Dropout(do)(n) if do else n
        n = Conv2D(dim, 3, activation=acti, padding='same')(n)
        n = BatchNormalization()(n) if bn else n
        return Concatenate()([m, n]) if res else n

    def level_block(tensor, dimension, depth, inc_rate, activation, dropout, bacthnorm, maxpool, upconv, residual):
        if depth > 0:
            n = conv_block(tensor, dimension, activation, bacthnorm, residual)
            tensor = MaxPooling2D()(n) if maxpool else Conv2D(dimension, 3, strides=2, padding='same')(n)
            tensor = level_block(
                tensor, int(inc_rate * dimension),
                depth - 1, inc_rate, activation, dropout, bacthnorm, maxpool, upconv, residual)
            if upconv:
                tensor = UpSampling2D()(tensor)
                tensor = Conv2D(dimension, 2, activation=activation, padding='same')(tensor)
            else:
                tensor = Conv2DTranspose(dimension, 3, strides=2, activation=activation, padding='same')(tensor)
            n = Concatenate()([n, tensor])
            tensor = conv_block(n, dimension, activation, bacthnorm, residual)
        else:
            tensor = conv_block(tensor, dimension, activation, bacthnorm, residual, dropout)
        return tensor

    def UNet(img_shape, out_ch, start_ch, depth, inc_rate, activation, dropout, batchnorm, maxpool, upconv, residual):
        inputs = Input(shape=img_shape)
        outputs = level_block(
            inputs, start_ch, depth, inc_rate, activation, dropout, batchnorm, maxpool, upconv, residual)
        outputs = Conv2D(out_ch, 1)(outputs)
        return Model(inputs=inputs, outputs=outputs)

    img_shape = [height, width, channels]
    model = UNet(img_shape, out_ch, start_ch, depth, inc_rate, activation, drop_out, batch_norm, maxpool, upconv, residual)

    return model


def build_model(height, width, channels, batch_norm=False, drop_out=0.0):
    inputs = Input((height, width, channels))
    s = Lambda(lambda x: x / 255)(inputs)

    c1 = Conv2D(8, (3, 3), activation='relu', padding='same')(s)
    c1 = BatchNormalization()(c1) if batch_norm else c1
    c1 = Dropout(drop_out)(c1) if drop_out != 0 else c1
    c1 = Conv2D(8, (3, 3), activation='relu', padding='same')(c1)
    c1 = BatchNormalization()(c1) if batch_norm else c1
    p1 = MaxPooling2D((2, 2))(c1)

    c2 = Conv2D(16, (3, 3), activation='relu', padding='same')(p1)
    c2 = BatchNormalization()(c2) if batch_norm else c2
    c2 = Dropout(drop_out)(c2) if drop_out != 0 else c2
    c2 = Conv2D(16, (3, 3), activation='relu', padding='same')(c2)
    c2 = BatchNormalization()(c2) if batch_norm else c2
    p2 = MaxPooling2D((2, 2))(c2)

    c3 = Conv2D(32, (3, 3), activation='relu', padding='same')(p2)
    c3 = BatchNormalization()(c3) if batch_norm else c3
    c3 = Dropout(drop_out)(c3) if drop_out != 0 else c3
    c3 = Conv2D(32, (3, 3), activation='relu', padding='same')(c3)
    c3 = BatchNormalization()(c3) if batch_norm else c3
    p3 = MaxPooling2D((2, 2))(c3)

    c4 = Conv2D(64, (3, 3), activation='relu', padding='same')(p3)
    c4 = BatchNormalization()(c4) if batch_norm else c4
    c4 = Dropout(drop_out)(c4) if drop_out != 0 else c4
    c4 = Conv2D(64, (3, 3), activation='relu', padding='same')(c4)
    c4 = BatchNormalization()(c4) if batch_norm else c4
    p4 = MaxPooling2D(pool_size=(2, 2))(c4)

    c5 = Conv2D(128, (3, 3), activation='relu', padding='same')(p4)
    c5 = BatchNormalization()(c5) if batch_norm else c5
    c5 = Dropout(drop_out)(c5) if drop_out != 0 else c5
    c5 = Conv2D(128, (3, 3), activation='relu', padding='same')(c5)
    c5 = BatchNormalization()(c5) if batch_norm else c5

    u6 = Conv2DTranspose(64, (2, 2), strides=(2, 2), padding='same')(c5)
    u6 = concatenate([u6, c4])
    c6 = Conv2D(64, (3, 3), activation='relu', padding='same')(u6)
    c6 = Conv2D(64, (3, 3), activation='relu', padding='same')(c6)

    u7 = Conv2DTranspose(32, (2, 2), strides=(2, 2), padding='same')(c6)
    u7 = concatenate([u7, c3])
    c7 = Conv2D(32, (3, 3), activation='relu', padding='same')(u7)
    c7 = Conv2D(32, (3, 3), activation='relu', padding='same')(c7)

    u8 = Conv2DTranspose(16, (2, 2), strides=(2, 2), padding='same')(c7)
    u8 = concatenate([u8, c2])
    c8 = Conv2D(16, (3, 3), activation='relu', padding='same')(u8)
    c8 = Conv2D(16, (3, 3), activation='relu', padding='same')(c8)

    u9 = Conv2DTranspose(8, (2, 2), strides=(2, 2), padding='same')(c8)
    u9 = concatenate([u9, c1], axis=3)
    c9 = Conv2D(8, (3, 3), activation='relu', padding='same')(u9)
    c9 = Conv2D(8, (3, 3), activation='relu', padding='same')(c9)

    outputs = Conv2D(1, (1, 1))(c9)

    model = Model(inputs=[inputs], outputs=[outputs])

    return model


def compile_model(model, optimizer='adam', loss='bce-dice', dice=False, weight_decay=0.0, exclude_bn=True):
    if loss == 'bce':
        _loss = weighted_binary_crossentropy
    elif loss == 'bce-dice':
        _loss = weighted_bce_dice_loss
    elif loss == 'lovasz':
        _loss = weighted_lovasz_hinge
    elif loss == 'lovasz-dice':
        _loss = weighted_lovasz_dice_loss
    elif loss == 'lovasz-inv':
        _loss = weighted_lovasz_hinge_inversed
    elif loss == 'lovasz-double':
        _loss = weighted_lovasz_hinge_double

    if weight_decay != 0.0:
        _l2_loss = l2_loss(weight_decay, exclude_bn)
        loss = lambda true, pred: _loss(true, pred) + _l2_loss
    else:
        loss = _loss
    model.compile(optimizer=optimizer, loss=loss, metrics=get_metrics())
    return model


if __name__ == '__main__':
    model = build_model(128, 128, 1)
    model.summary()
