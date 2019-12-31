import scipy.optimize as sco
from sklearn.decomposition import PCA
import pandas as pd
import numpy as np
from keras.layers import Input, Dense
from keras.models import Model
from keras import regularizers
from keras.models import load_model

from statsmodels.tsa.api import ExponentialSmoothing, SimpleExpSmoothing, Holt
from ._helper import portfolio_create
from ._hrpfuncs import *

class HRPOpt:

    def __init__(
                 self,
                 portfolio_size,
                 allow_short = True,
                 ):
        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.input_shape = (portfolio_size, portfolio_size, )

    def act(self, returns):
        corr = returns.corr()
        cov = returns.cov()
        optimal_weights = getHRP(cov, corr)

        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)
        return optimal_weights

class AutoencoderOpt:

    def __init__(
                     self,
                     portfolio_size,
                     allow_short = True,
                     encoding_dim = 25
                 ):

        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.encoding_dim = encoding_dim

    def model(self, input_size = None):
        if input_size is None:
            input_size = self.portfolio_size
        input_img = Input(shape=(input_size, ))
        encoded = Dense(self.encoding_dim, activation='relu', kernel_regularizer=regularizers.l2(1e-6))(input_img)
        decoded = Dense(input_size, activation= 'linear', kernel_regularizer=regularizers.l2(1e-6))(encoded)
        autoencoder = Model(input_img, decoded)
        autoencoder.compile(optimizer='adam', loss='mse')
        return autoencoder


    def act(self, returns, input_size = None):
        data = returns
        autoencoder = self.model(input_size)
        autoencoder.fit(data, data, shuffle=False, epochs=25, batch_size=32, verbose=False)
        reconstruct = autoencoder.predict(data)

        communal_information = []

        for i in range(0, len(returns.columns)):
            diff = np.linalg.norm((returns.iloc[:,i] - reconstruct[:,i])) # 2 norm difference
            communal_information.append(float(diff))

        optimal_weights = np.array(communal_information) / sum(communal_information)
        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            """
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)
            """
            rank_weights = np.abs(optimal_weights)
            ranked_idx   = np.argsort(rank_weights)
            up_idx      = ranked_idx[:30]
            #up_idx       = ranked_idx[45:]
            optimal_weights = np.array([0.0]*rank_weights.shape[0])
            #for idx in low_idx:
                #optimal_weights[idx] = 1.0
            for idx in up_idx:
                optimal_weights[idx] = 1.0
            optimal_weights /= sum(optimal_weights)
        return optimal_weights

class SmoothingOpt:

    def __init__(
                     self,
                     portfolio_size,
                     allow_short = True,
                     forecast_horizon = 252,
                 ):

        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.forecast_horizon = forecast_horizon

    def act(self, timeseries):

        optimal_weights = []

        for asset in timeseries.columns:
            ts = timeseries[asset]
            fit1 = Holt(ts).fit()
            forecast = fit1.forecast(self.forecast_horizon)
            prediction = forecast.values[-1] - forecast.values[0]
            optimal_weights.append(prediction)

        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)
        return optimal_weights

class PCAOpt:
    def __init__(
                     self,
                     portfolio_size,
                     pc_id = 0,
                     pca_max = 10,
                     allow_short = False,
                 ):

        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.input_shape = (portfolio_size, portfolio_size, )
        self.pc_id = pc_id
        self.pc_max = pca_max

    def act(self, returns):
        C = self.pc_max
        pca = PCA(C)
        _ = pca.fit_transform(returns)
        pcs = pca.components_

        pc1 = pcs[self.pc_id, :]
        optimal_weights = pc1
        if self.allow_short:
            optimal_weights = optimal_weights / sum(np.abs(pc1))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)

        return optimal_weights

class MaxReturnsOpt:

    def __init__(
                     self,
                     portfolio_size,
                     allow_short = False,
                 ):

        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.input_shape = (portfolio_size, portfolio_size, )


    def act(self, returns):

        def loss(weights):
            return -portfolio_create(returns, weights)[0]

        n_assets = len(returns.columns)

        if self.allow_short:
            bnds = tuple((-1.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(np.abs(x))})
        else:
            bnds = tuple((0.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(x)})


        opt_S = sco.minimize(
            loss,
            n_assets * [1.0 / n_assets],
            method = 'SLSQP', bounds = bnds,
            constraints = cons)

        optimal_weights = opt_S['x']

        # sometimes optimization fails with constraints, need to be fixed by hands
        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)

        return optimal_weights

class MinVarianceOpt:

    def __init__(
                     self,
                     portfolio_size,
                     allow_short = False,
                 ):
        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.input_shape = (portfolio_size, portfolio_size, )


    def act(self, returns):
        def loss(weights):
            return portfolio_create(returns, weights)[1]**2
        n_assets = len(returns.columns)
        if self.allow_short:
            bnds = tuple((-1.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(np.abs(x))})
        else:
            bnds = tuple((0.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(x)})

        opt_S = sco.minimize(
            loss,
            n_assets * [1.0 / n_assets],
            method = 'SLSQP', bounds = bnds,
            constraints = cons)

        optimal_weights = opt_S['x']
        # sometimes optimization fails with constraints, need to be fixed by hands
        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)
        return optimal_weights

class MaxSharpeOpt:
    def __init__(
                     self,
                     portfolio_size,
                     allow_short = False,
                 ):

        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.input_shape = (portfolio_size, portfolio_size, )


    def act(self, returns):

        def loss(weights):
            return -portfolio_create(returns, weights)[2]

        n_assets = len(returns.columns)

        if self.allow_short:
            bnds = tuple((-1.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(np.abs(x))})
        else:
            bnds = tuple((0.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(x)})

        opt_S = sco.minimize(
            loss,
            n_assets * [1.0 / n_assets],
            method = 'SLSQP', bounds = bnds,
            constraints = cons)

        optimal_weights = opt_S['x']

        # sometimes optimization fails with constraints, need to be fixed by hands
        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)

        return optimal_weights

class MaxDecorrelationOpt:

    def __init__(
                     self,
                     portfolio_size,
                     allow_short = False,
                 ):

        self.portfolio_size = portfolio_size
        self.allow_short = allow_short
        self.input_shape = (portfolio_size, portfolio_size, )


    def act(self, returns):

        def loss(weights):
            weights = np.array(weights)
            return np.sqrt(np.dot(weights.T, np.dot(returns.corr(), weights)))

        n_assets = len(returns.columns)

        if self.allow_short:
            bnds = tuple((-1.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(np.abs(x))})
        else:
            bnds = tuple((0.0, 1.0) for x in range(n_assets))
            cons =({'type': 'eq', 'fun': lambda x : 1.0 - np.sum(x)})


        opt_S = sco.minimize(
            loss,
            n_assets * [1.0 / n_assets],
            method = 'SLSQP', bounds = bnds,
            constraints = cons)

        optimal_weights = opt_S['x']

        # sometimes optimization fails with constraints, need to be fixed by hands
        if self.allow_short:
            optimal_weights /= sum(np.abs(optimal_weights))
        else:
            optimal_weights += np.abs(np.min(optimal_weights))
            optimal_weights /= sum(optimal_weights)
        return optimal_weights