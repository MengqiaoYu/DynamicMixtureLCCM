from sklearn.linear_model import LogisticRegression
import scipy.stats as stat
import numpy as np

__author__ = "Mengqiao Yu"
__email__ = "mengqiao.yu@berkeley.edu"

class TransitionModel():
    """Variant of Multinomial Logit Model"""

    def __init__(self, intercept_fit=False, std_fit=True, num_states=2, num_covariates=0):
        """
        Parameters
        ----------
        num_covariates doesn't include constant.
        """
        self.intercept_fit = intercept_fit
        self.std_fit = std_fit
        self.num_states = num_states
        self.model = LogisticRegression(solver='lbfgs',
                                        fit_intercept=self.intercept_fit,
                                        warm_start=True)

        # Trick: initialize covariates as zero (for first e_step).
        self.model.fit(np.ones((self.num_states, num_covariates + 1)),
                       np.arange(self.num_states))

    def _data_formatter(self, X, y):
        """
        reformat/augment data matrix to fit multinomial logit model with prob output.
        Parameters
        ----------
        X: np array (num_seq * T , num of covariates)
        y: np array (num_seq * T , num of states) in prob but not discrete choice!
        Returns
        ----------
        X_augmented: (num_seq * T * num of states, num of covariates + 1)
        y_augmented: (num_seq * T * num of states, ) as discrete choice
        sample_weight: (num of obs * num of states, )
        """
        X = np.vstack(X)
        num_obs, num_states = X.shape[0], y.shape[1]
        X_augmented = np.repeat(X, num_states, axis=0)
        X_augmented = self._add_constant(X_augmented)
        y_augmented = np.tile(np.arange(num_states), num_obs)
        sample_weight = y.reshape(-1, )

        return X_augmented, y_augmented, sample_weight

    def _add_constant(self, X):
        """add constant to the first column"""
        return np.hstack((np.ones((X.shape[0], 1)), X))

    def fit(self, X, y):
        """
        estimate covariates in transition model
        Parameters
        ----------
        X: np array (num_seq * T , num of covariates)
        y: np array (num_seq * T , num of states) in prob.
        self.X: (num_seq * T * num of states, num of covariates + 1)
        self.y: (num_seq * T * num of states, ) as discrete choice.
        self.sample_weight: (num of obs * num of states, )
        """
        num_states = y.shape[1]
        multi_class = 'multinomial' if num_states >= 3 else 'ovr'
        self.model.multi_class = multi_class
        self.X, self.y, self.sample_weight = self._data_formatter(X, y)
        self.model.fit(self.X, self.y, sample_weight=self.sample_weight)

    def predict_log_proba(self, X):
        """For external use, for example, calculate the trend."""
        X = self._add_constant(X)
        return self.model.predict_log_proba(X)

    def get_params(self):
        if self.num_states == 2:
            return self.model.coef_ # The first value is intercept
        if self.num_states >= 3:
            # The first state is the base.
            return self.model.coef_[1:] - self.model.coef_[0]

    def get_std(self):
        """
        Calculate standard errors at the last step to save time.

        Returns:
        ----------
        std: standard error of each coefficient.
            (number of states - 1, number of covariates)
        p value: used for significance check.
                (number of states - 1, number of covariates)
        Notes:
        ----------
        (1) we separate binary and multinomial cases.
        (2) we deal with sample weights.
        """

        num_coef = self.model.coef_.size
        num_covariates = self.model.coef_.shape[1]
        if self.num_states == 2:
            # predProbs: (num_seq * T * num of states, num of states)
            predProbs = self.model.predict_proba(self.X)

            # W: (num_seq * T * num of states, num_seq * T * num of states)
            W = np.diagflat(np.product(predProbs, axis=1) * self.sample_weight)

            # cov_matrix: (num of covariates, num of covariates)
            cov_matrix = np.linalg.inv(np.dot(np.dot(self.X.T, W), self.X))

            std = np.sqrt(np.diag(cov_matrix))
            z_scores = self.model.coef_/std
            p_values = np.array([stat.norm.sf(abs(z)) * 2 for z in z_scores])

        if self.num_states >= 3:
            # predProbs: (num_seq * T * num of states, num of states)
            predProbs = self.model.predict_proba(self.X)

            # Initialize Fisher information matrix
            info_matrix = np.zeros((num_coef, num_coef))

            # Calculate variance-covariance matrix
            for i in range(self.num_states):
                for j in range(self.num_states):
                    if i == j:
                        W_i_j = np.diag(np.multiply(predProbs[:, i]
                                                    * (1.0 - predProbs[:, i]),
                                                    self.sample_weight))
                    else:
                        W_i_j = -np.diag(predProbs[:, i]
                                          * predProbs[:, j]
                                          * self.sample_weight)

                    info_i_j = np.dot(np.dot(self.X.T, W_i_j), self.X)
                    info_matrix[i * num_covariates : (i + 1) * num_covariates,
                    j * num_covariates : (j + 1) * num_covariates] = info_i_j
            # Note: we set the first state as the base.
            cov_matrix = np.linalg.inv(info_matrix[num_covariates:,
                                       num_covariates:])
            std = np.sqrt(np.diag(cov_matrix))
            z_scores = self.model.coef_.flatten()[num_covariates:, ]/std
            p_values = np.array([stat.norm.sf(abs(z))*2 for z in z_scores])

        return std.reshape((self.num_states - 1, -1)), \
               p_values.reshape((self.num_states - 1, -1))

class LogitChoiceModel():
    """Binary or Multinomial Logit Model"""

    def __init__(self, intercept_fit=False,
                 std_fit=True,
                 num_choices=2,
                 num_covariates=1):
        self.std_fit = std_fit
        self.num_choices = num_choices
        self.model = LogisticRegression(solver='lbfgs',
                                        fit_intercept=intercept_fit,
                                        warm_start=True)

        # Trick: initialize covariates based on random sample on prob.
        init_prob = np.random.dirichlet(np.ones(num_choices), size=1)
        init_sample = (init_prob * 1000).astype(int)
        self.model.fit(np.ones((np.sum(init_sample), num_covariates)),
                       np.repeat(np.arange(num_choices), init_sample.reshape(-1), axis = 0))

    def fit(self, X, y, sample_weight):
        multi_class = 'multinomial' if self.num_choices >= 3 else 'ovr'
        self.model.multi_class = multi_class
        self.X = X
        self.y = y
        self.sample_weight = sample_weight
        self.model.fit(X, y, sample_weight)

    def predict_log_proba(self, X):
        return self.model.predict_log_proba(X)

    def get_params(self):
        """Return both the coefficients and probability"""
        if self.num_choices == 2:
            return self.model.coef_, self.model.predict_proba(1)
        if self.num_choices >= 3:
            return self.model.coef_[1:], self.model.predict_proba(1)

    def get_std(self):
        """
        Calculate standard errors at the last step to save time.
        Returns:
        ----------
        std: standard error of each coefficient.
            (number of states - 1, number of covariates)
        p value: used for significance check.
                (number of states - 1, number of covariates)
        Notes:
        ----------
        (1) we separate binary and multinomial cases.
        (2) we deal with sample weights.
        """

        num_coef = self.model.coef_.size
        num_covariates = self.model.coef_.shape[1] # actually is 1
        if self.num_choices == 2:
            # predProbs: (num_seq * T * num of states, num of states)
            predProbs = self.model.predict_proba(self.X)

            # W: (num_seq * T * num of states, num_seq * T * num of states)
            W = np.diagflat(np.product(predProbs, axis=1) * self.sample_weight)

            # cov_matrix: (num of covariates, num of covariates)
            cov_matrix = np.linalg.inv(np.dot(np.dot(self.X.T, W), self.X))

            std = np.sqrt(np.diag(cov_matrix))
            z_scores = self.model.coef_/std
            p_values = np.array([stat.norm.sf(abs(z)) * 2 for z in z_scores])

        if self.num_choices >= 3:
            # predProbs: (num_seq * T * num of states, num of states)
            predProbs = self.model.predict_proba(self.X)

            # Initialize Fisher information matrix
            info_matrix = np.zeros((num_coef, num_coef))

            # Calculate variance-covariance matrix
            for i in range(self.num_choices):
                for j in range(self.num_choices):
                    if i == j:
                        W_i_j = np.diag(np.multiply(predProbs[:, i]
                                                    * (1.0 - predProbs[:, i]),
                                                    self.sample_weight))
                    else:
                        W_i_j = -np.diag(predProbs[:, i]
                                          * predProbs[:, j]
                                          * self.sample_weight)

                    info_i_j = np.dot(np.dot(self.X.T, W_i_j), self.X)
                    info_matrix[i * num_covariates : (i + 1) * num_covariates,
                    j * num_covariates : (j + 1) * num_covariates] = info_i_j
            # Note: we set the first state as the base.
            cov_matrix = np.linalg.inv(info_matrix[num_covariates:,
                                       num_covariates:])
            std = np.sqrt(np.diag(cov_matrix))
            z_scores = self.model.coef_.flatten()[num_covariates:, ]/std
            p_values = np.array([stat.norm.sf(abs(z))*2 for z in z_scores])

        return std.reshape((self.num_choices - 1, -1)), \
               p_values.reshape((self.num_choices - 1, -1))