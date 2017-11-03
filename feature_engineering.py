#!/usr/bin/python
# -*- coding: utf-8 -*-
""" Most of this code is from Nir Malbin's notebook: https://www.kaggle.com/donniedarko/darktaxi-tripdurationprediction-lb-0-385 """

from sklearn.model_selection import train_test_split
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import PCA
from sklearn import preprocessing
import pandas as pd
import numpy as np
import shutil
import os

from joblib import Memory

__all__ = ['load_data']


def _geohash(features, prefix, longitude, latitude, precision):
    """ Encode a (lon, lat) pair to a GeoHash.
        Code inspired from https://github.com/transitland/mapzen-geohash/blob/master/mzgeohash/geohash.py
    """

    def _float_to_bits(value, lower, upper):
        """ Convert a float to a list of GeoHash bits """
        middle = 0.0
        for bit in range(int(precision / 2)):
            fname = prefix + str(bit)
            if fname not in features:
                features[fname] = []
            byte = 0
            for bit in range(5):
                if value >= middle:
                    lower = middle
                    byte += 2**bit
                else:
                    upper = middle
                middle = (upper + lower) / 2
            features[fname].append(byte)

    # Half the length for each component.
    _float_to_bits(longitude, lower=-180.0, upper=180.0)
    _float_to_bits(latitude, lower=-90.0, upper=90.0)


def _clustering(coords, df_all):
    kmeans = MiniBatchKMeans(n_clusters=8**2, batch_size=32**3).fit(coords)
    df_all['pickup_cluster'] = kmeans.predict(df_all[['pickup_latitude', 'pickup_longitude']])
    df_all['dropoff_cluster'] = kmeans.predict(df_all[['dropoff_latitude', 'dropoff_longitude']])
    df_all['pickup_datetime_group'] = df_all['pickup_datetime'].dt.round('60min')


def _osrm(datadir):
    features = ['total_distance', 'total_travel_time', 'number_of_steps']
    fr1 = pd.read_csv(os.path.join(datadir, 'osrm/fastest_routes_train_part_1.csv'), usecols=['id', *features])
    fr2 = pd.read_csv(os.path.join(datadir, 'osrm/fastest_routes_train_part_2.csv'), usecols=['id', *features])
    test_street_info = pd.read_csv(os.path.join(datadir, 'osrm/fastest_routes_test.csv'), usecols=['id', *features])
    train_street_info = pd.concat((fr1, fr2))
    return train_street_info, test_street_info, features


def _haversine(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    AVG_EARTH_RADIUS = 6371  # in km
    lat = lat2 - lat1
    lng = lng2 - lng1
    d = np.sin(lat * 0.5) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(lng * 0.5) ** 2
    h = 2 * AVG_EARTH_RADIUS * np.arcsin(np.sqrt(d))
    return h


def _manhattan(lat1, lng1, lat2, lng2):
    a = _haversine(lat1, lng1, lat1, lng2)
    b = _haversine(lat1, lng1, lat2, lng1)
    return a + b


def load_data(datadir, trainset, testset, valid_size, output_size, cache_read_only):
    if cache_read_only:
        dest = '/output/cache'
        shutil.copytree(datadir, dest)
        datadir = dest
    memory = Memory(cachedir=os.path.join(datadir, 'cache'))

    @memory.cache(ignore=['datadir'])
    def _cached_load_data(datadir, trainset, testset, valid_size):
        features = ['vendor_id', 'passenger_count', 'pickup_latitude', 'pickup_longitude', 'dropoff_latitude', 'dropoff_longitude', 'pickup_pca0', 'pickup_pca1', 'hour',
                    'dropoff_pca0', 'dropoff_pca1', 'pca_manhattan', 'month', 'weekofyear', 'weekday', 'seconds', 'week_delta', 'week_hour', 'week_delta_sin', 'hour_sin',
                    'manhattan', 'haversine']
        df_all = pd.concat((pd.read_csv(os.path.join(datadir, trainset)), pd.read_csv(os.path.join(datadir, testset))))
        df_all['pickup_datetime'] = df_all['pickup_datetime'].apply(pd.Timestamp)
        df_all['dropoff_datetime'] = df_all['dropoff_datetime'].apply(pd.Timestamp)
        df_all['trip_duration_log'] = np.log(df_all['trip_duration'] + 1)

        # Remove abnormal locations for PCA training
        coords = np.vstack((df_all[['pickup_latitude', 'pickup_longitude']], df_all[['dropoff_latitude', 'dropoff_longitude']]))
        min_lat, min_lng = coords.mean(axis=0) - coords.std(axis=0)
        max_lat, max_lng = coords.mean(axis=0) + coords.std(axis=0)
        coords = coords[(coords[:, 0] > min_lat) & (coords[:, 0] < max_lat) & (coords[:, 1] > min_lng) & (coords[:, 1] < max_lng)]

        # Get PCA features on location
        pca = PCA().fit(coords)
        df_all['pickup_pca0'] = pca.transform(df_all[['pickup_latitude', 'pickup_longitude']])[:, 0]
        df_all['pickup_pca1'] = pca.transform(df_all[['pickup_latitude', 'pickup_longitude']])[:, 1]
        df_all['dropoff_pca0'] = pca.transform(df_all[['dropoff_latitude', 'dropoff_longitude']])[:, 0]
        df_all['dropoff_pca1'] = pca.transform(df_all[['dropoff_latitude', 'dropoff_longitude']])[:, 1]
        df_all['pca_manhattan'] = (df_all['dropoff_pca0'] - df_all['pickup_pca0']).abs() + (df_all['dropoff_pca1'] - df_all['pickup_pca1']).abs()

        # Distances
        df_all['haversine'] = _haversine(df_all['pickup_latitude'].values, df_all['pickup_longitude'].values,
                                         df_all['dropoff_latitude'].values, df_all['dropoff_longitude'].values)
        df_all['manhattan'] = _manhattan(df_all['pickup_latitude'].values, df_all['pickup_longitude'].values,
                                         df_all['dropoff_latitude'].values, df_all['dropoff_longitude'].values)

        # Date times
        df_all['month'] = df_all['pickup_datetime'].dt.month
        df_all['weekofyear'] = df_all['pickup_datetime'].dt.weekofyear
        df_all['weekday'] = df_all['pickup_datetime'].dt.weekday
        df_all['hour'] = df_all['pickup_datetime'].dt.hour
        df_all['week_delta'] = df_all['pickup_datetime'].dt.weekday \
            + ((df_all['pickup_datetime'].dt.hour + (df_all['pickup_datetime'].dt.minute / 60.0)) / 24.0)
        df_all['week_hour'] = df_all['weekday'] * 24. + df_all['hour']
        df_all['seconds'] = df_all['pickup_datetime'].dt.second + df_all['pickup_datetime'].dt.minute * 60.

        # Make time features cyclic
        df_all['week_delta_sin'] = np.sin((df_all['week_delta'] / 7) * np.pi)**2
        df_all['hour_sin'] = np.sin((df_all['hour'] / 24) * np.pi)**2

        # Traffic (Count trips over 60min)
        df_counts = df_all.set_index('pickup_datetime')[['id']].sort_index()
        df_all = df_all.merge(df_counts, on='id', how='left')

        # K means clustering
        _clustering(coords, df_all)

        # Geohash
        precision = 12
        geohash_features = {}
        for _, row in df_all.iterrows():
            _geohash(geohash_features, 'pickup_geohash_', row['pickup_latitude'], row['pickup_longitude'], precision=precision)
            _geohash(geohash_features, 'dropoff_geohash_', row['dropoff_latitude'], row['dropoff_longitude'], precision=precision)
        df_all = df_all.join(pd.DataFrame(geohash_features))
        features.extend(list(geohash_features.keys()))

        # Get test set and train set from df_all
        X_train = df_all[df_all['trip_duration'].notnull()]
        y_train = df_all[df_all['trip_duration'].notnull()]['trip_duration_log'].values.flatten()
        X_test = df_all[df_all['trip_duration'].isnull()]
        test_ids = df_all[df_all['trip_duration'].isnull()]['id'].values

        # Add OSRM data
        train_street_info, test_street_info, osrm_features = _osrm(datadir)
        features.extend(osrm_features)
        X_train = X_train.merge(train_street_info, how='left', on='id')[features]
        X_test = X_test.merge(test_street_info, how='left', on='id')[features]

        # Fill missing osrm data
        mean_distance, mean_travel_time, mean_steps = X_train.total_distance.mean(), X_train.total_travel_time.mean(), X_train.number_of_steps.mean()

        def _fillnan(df):
            df.total_distance = df.total_distance.fillna(mean_distance)
            df.total_travel_time = df.total_travel_time.fillna(mean_travel_time)
            df.number_of_steps = df.number_of_steps.fillna(round(mean_steps))
        _fillnan(X_train)
        _fillnan(X_test)

        # Split dataset into trainset and testset
        train_data, valid_data, train_targets, valid_targets = train_test_split(X_train.values, y_train, test_size=valid_size, random_state=459)

        # Normalize feature columns
        standardizer = preprocessing.StandardScaler()
        train_data = standardizer.fit_transform(train_data)
        valid_data = standardizer.transform(valid_data)
        test_data = standardizer.transform(X_test.values)

        return len(features), (test_ids, test_data), (train_data, valid_data, train_targets, valid_targets)

    @memory.cache
    def _bucketize(train_targets, valid_targets, bucket_count):
        """ Process buckets from train targets and deduce labels of trainset and testset """
        sorted_targets = np.sort(train_targets)
        bucket_size = len(sorted_targets) // bucket_count
        buckets = [sorted_targets[i * bucket_size: (1 + i) * bucket_size] for i in range(bucket_count)]
        bucket_maxs = [np.max(b) for b in buckets]
        bucket_maxs[-1] = float('inf')

        # Bucketize targets (labels are bucket indices)
        def _find_indice(value): return np.searchsorted(bucket_maxs, value)
        train_labels = np.vectorize(_find_indice)(train_targets)
        valid_labels = np.vectorize(_find_indice)(valid_targets)
        # Process buckets means
        buckets_means = [np.mean(bucket) for bucket in buckets]
        return train_labels, valid_labels, buckets_means

    # TODO: Before removing this method, make further experiments to make sure using soft classes doesn't improve performances
    @memory.cache
    def _bucketize_soft_classes(train_targets, valid_targets, bucket_count):
        """ Process buckets from train targets and deduce labels of trainset and testset """
        sorted_targets = np.sort(train_targets)
        bucket_size = len(sorted_targets) // bucket_count
        buckets = [sorted_targets[i * bucket_size: (1 + i) * bucket_size] for i in range(bucket_count)]
        buckets_means = np.asarray([np.mean(bucket) for bucket in buckets])
        bucket_maxs = [np.max(b) for b in buckets]
        bucket_maxs[-1] = float('inf')

        def _gauss(mu):
            idx = np.searchsorted(bucket_maxs, mu)
            sigma = (np.max(buckets[idx]) - np.min(buckets[idx])) / 2.
            soft_classes = np.exp(-((buckets_means - mu)**2 / (2.0 * sigma**2)))
            distrib_sum = np.sum(soft_classes)
            if distrib_sum > 0. and not np.isnan(soft_classes).any():
                soft_classes /= distrib_sum
            soft_classes[idx] += 1. - np.nansum(soft_classes)
            return soft_classes
        train_labels = np.asarray([_gauss(t) for t in train_targets])
        valid_labels = np.asarray([_gauss(t) for t in valid_targets])
        return train_labels, valid_labels, buckets_means

    # Parse and preprocess data
    features_len, (test_ids, testset), (train_data, valid_data, train_targets, valid_targets) = _cached_load_data(datadir, trainset, testset, valid_size)

    # Get buckets from train targets
    train_labels, valid_labels, bucket_means = _bucketize(train_targets, valid_targets, output_size)

    return features_len, (test_ids, testset), (train_data, valid_data, train_targets, valid_targets, train_labels, valid_labels), bucket_means
