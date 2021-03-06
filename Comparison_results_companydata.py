
from numpy import savez_compressed, load

import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_curve
from sklearn.neighbors import KNeighborsClassifier
import random
import matplotlib.patheffects as PathEffects
from sklearn.metrics.pairwise import pairwise_distances, linear_kernel
from random import sample
import time

from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import csr_matrix
from sklearn.decomposition import NMF
import surprise
from fuzzywuzzy import fuzz
from sklearn.neighbors import NearestNeighbors


import tensorflow as tf
from keras.layers import Input, Conv2D, Lambda, Dense, Flatten,MaxPooling2D, concatenate

from keras.models import Model, Sequential
from keras.regularizers import l2
from keras import backend as K
from keras.optimizers import SGD,Adam
from keras.losses import binary_crossentropy
import os
import pickle
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.svm import SVC
from sklearn.preprocessing import normalize


import spacy
import en_core_web_sm  # large 
# en_core_web_sm

import re

from nltk.stem import PorterStemmer
# nltk.download('punkt')
from nltk.tokenize import sent_tokenize, word_tokenize


article_filename = sys.argv[1]
click_filename = sys.argv[2]
sub_n = int(sys.argv[3])
top_n = int(sys.argv[4])
eval_num = int(sys.argv[5])
k = int(sys.argv[6])
nseed = int(sys.argv[7])

# print(type(sub_n), type(top_n))


top_time = time.time()

df_articles = pd.read_csv(article_filename, names= ['articleId', 'title', 'category'], header=0)
df_articles = df_articles.drop_duplicates('articleId', keep='first').reset_index(drop= True)

## Data preprocessing: 
# (1) drop NaNs
df_articles = df_articles.dropna()
# (2) deduplication
df_articles = df_articles[df_articles['articleId'] != '0']

df_articles = df_articles.drop_duplicates('articleId').reset_index(drop=True)

print('Article content file (articleId, title, category): shape = {}'.format(df_articles.shape))


# 2. User behavior:
#    columns: 
#           userId (string)
#           articleId (string)

df_clicks = pd.read_csv(click_filename, names = ['userId', 'articleId'], header = 0)
## Data preprocessing: 
# (1) drop NaNs
df_clicks = df_clicks.dropna()
# (2) deduplication
df_clicks = df_clicks[df_clicks['articleId'] != '0']
df_clicks = df_clicks.drop_duplicates().reset_index(drop = True)

print('User behavior file (userId, articleId): shape = {}'.format(df_clicks.shape))


"""
	# Break up the big title context string into string array of words

		- word tokenize
		- stemming
		- filter out punctuation
		- remove stop words

"""


ps = PorterStemmer()


### Convert raw content into word vectors
nlp = en_core_web_sm.load()
# import the list of stop words from the spacy library
from spacy.lang.en.stop_words import STOP_WORDS

def remove_stop_words(text):
    return ' '.join([word for word in text.split(' ') if word.lower() not in STOP_WORDS])
# print(remove_stop_words('why is my dog on the drugs'))

# get word vector for a list of words
def get_word_vec(l): # l: a list of words
    return nlp(remove_stop_words(' '.join(l))).vector

p_wv = len(get_word_vec(['word']))

print(p_wv)


## Raw title/body context:
# Break up the big title/body context string into a string array of words
# df_articles['title'] = df_articles['title'].apply(lambda x: \
#                             [ps.stem(w) for w in word_tokenize(x) if w.isalpha() and w.lower() not in STOP_WORDS])


df_articles['title'] = df_articles['title'].apply(lambda x: re.findall(r'\w+', x.lower()))
# df_articles['body'] = df_articles['body'].apply(lambda x: re.findall(r'\w+', x))

# Sort by articleId
df_articles = df_articles.sort_values(by = 'articleId').reset_index(drop = True)


"""

	Sample small dataset

"""

np.random.seed(nseed)

sub_articleIds = np.random.choice(df_clicks['articleId'].value_counts()[:top_n].index, sub_n, replace = False)


# sub_articleIds = list(pd.DataFrame(df_clicks['articleId'].value_counts(\
#                         )).iloc[:top_n].sample(sub_n, replace = False, random_state = 123).index.values)

df_articles = df_articles[df_articles.articleId.isin(sub_articleIds)].reset_index(drop=True)
df_clicks = df_clicks[df_clicks.articleId.isin(df_articles.articleId)].reset_index(drop=True)

print(df_articles.shape, df_clicks.shape)

# df_articles.to_csv('sub_articles_{}.csv'.format(sub_n), header = False)
# df_clicks.to_csv('sub_clicks_{}.csv'.format(sub_n), header = False)


# Combine article content and clicks dataset
df_combine = pd.merge(df_clicks, df_articles, how = 'inner', on = 'articleId')
#print(df_combine.shape)

#print(len(df_combine.articleId.unique()), len(df_combine.userId.unique())) # get number of unique articles and unique users

### Start converting
start_time = time.time()

article_title_wv = pd.DataFrame(0, index = df_articles['articleId'], columns = range(p_wv))
# article_body_wv = pd.DataFrame(0, index = df_articles['articleId'], columns = range(p_wv))

for i in range(df_articles.shape[0]):
    article_title_wv.loc[df_articles['articleId'][i], :] = pd.Series(get_word_vec(df_articles['title'][i]))
#     article_body_wv.loc[df_articles['articleId'][i], :] = pd.Series(get_word_vec(df_articles['body'][i]))

# article_concat_wv = pd.concat([article_title_wv, article_body_wv], axis = 1)
# article_concat_wv.columns = range(article_concat_wv.shape[1])
# print(article_concat_wv.shape)

print('Running time for converting raw content into word vectors: {} seconds'.format(round(time.time() - start_time, 2)))



'''

    Construct co-watched graph for articles:
        - Node: articles
        - Edge: weighted by co-watch frequency

'''
df_user_data = df_combine[['userId', 'articleId']]
df_user_data = df_user_data.sort_values(by = 'articleId').reset_index(drop = True)
df_user_data.head()


# Construct a user dictionary where the key is the articleId and the values are the userIds who watched this article
start_time = time.time()

d_user = {}

for i in range(df_user_data.shape[0]):
    if df_user_data['articleId'][i] not in d_user:
        d_user[df_user_data['articleId'][i]] = set()
    else:
        d_user[df_user_data['articleId'][i]].add(df_user_data['userId'][i])

print(len(d_user))

print('Running time: {} seconds'.format(round(time.time() - start_time, 2)))


# Create article-by-article user co-watched matrix
#   - cell_{i, j}: # of users who watched both article i and j


n_articles = len(df_articles['articleId'])
cowatched_mat = np.zeros((n_articles, n_articles))

start_time = time.time()

for r in range(n_articles):
    for c in range(r+1, n_articles):
        if d_user.get(df_articles['articleId'][r]) == None or d_user.get(df_articles['articleId'][c]) == None:
            cowarched_mat[r, c] = 0
        else:
            cowatched_mat[r, c] = len(d_user[df_articles['articleId'][r]].intersection(d_user[df_articles['articleId'][c]]))
#     if r%100 == 0:
#         print(r, time.time() - start_time)
# Co-watched matrix: symmetric
cowatched_mat_s = cowatched_mat + cowatched_mat.T
print(cowatched_mat_s[:5, :5])

print('running time for creating co-watch matrix: {} seconds'.format(round(time.time()-start_time, 2)))


print("Cowatched matrix max and mean = ", cowatched_mat_s.max(), cowatched_mat_s.mean())


'''
    CDML: 
        - Input: content feature vectors
        - Output: embedding feature vectors

    1. early fusion
    2. late fusion
'''

## Construct a list of all article index pairs with 
#       - number of cowatched >= some threshold
#       - and articles come from different category
## Construct a dictionary with 
#       - key = article index, 
#       - and values = set of index who have # of cowatched = 0 
#       - and from different category

start_time = time.time()

num_threshold = 1
cowatched_list = []
zero_cowatched_dict = {}

for r in range(cowatched_mat_s.shape[0]):
    zero_cowatched_dict[r] = set(c for c in range(cowatched_mat_s.shape[0]) \
                                 if cowatched_mat_s[r, c] == 0 and r != c and df_articles.iloc[r]['category'] != df_articles.iloc[c]['category'])
    if r%100 == 0:
        print(r, time.time() - start_time)
    for c in range(r+1, cowatched_mat_s.shape[1]):
        if cowatched_mat_s[r, c] >= num_threshold and df_articles.iloc[r]['category'] != df_articles.iloc[c]['category']:
            cowatched_list.append((r, c))


print('running time for constructing cowatched lists for each user: {} seconds'.format(round(time.time() - start_time, 2)))


# Generate triplets
def generate_triplet(x_feature, cowatched_list, zero_cowatched_dict, ap_pairs, an_pairs, testsize):
 
    #ap_pairs, an_pairs = 10, 10
    #testsize = 0.2 

    trainsize = 1 - testsize
    triplet_train_pairs = []
    triplet_test_pairs = []

    A_P_pairs = random.sample(cowatched_list, k = ap_pairs)
    Neg_idx = []
    for p in range(len(A_P_pairs)):
        Neg_idx.append(sample(zero_cowatched_dict[A_P_pairs[p][0]].intersection(zero_cowatched_dict[A_P_pairs[p][1]]), 1)[0])

    # Train
    A_P_len = len(A_P_pairs)
    Neg_len = len(Neg_idx)
    train_i = 0
    for ap in A_P_pairs[:int(A_P_len*trainsize)]:
        # print(ap, train_i)
        Anchor = x_feature[ap[0]]
        Positive = x_feature[ap[1]]
        Negative = x_feature[Neg_idx[train_i]]
        triplet_train_pairs.append([Anchor, Positive, Negative])
        train_i += 1

    # Test
    test_i = int(A_P_len*trainsize)
    for ap in A_P_pairs[int(A_P_len*trainsize):]:
        #print(ap, test_i)
        Anchor = x_feature[ap[0]]
        Positive = x_feature[ap[1]]
        Negative = x_feature[Neg_idx[test_i]]
        triplet_test_pairs.append([Anchor, Positive, Negative])
        test_i += 1
    
    return np.array(triplet_train_pairs), np.array(triplet_test_pairs)


# Define triplet loss
def triplet_loss(y_true, y_pred, alpha = 0.4):
    """
    Implementation of the triplet loss function
    Arguments:
    y_true -- true labels, required when you define a loss in Keras, you don't need it in this function.
    y_pred -- python list containing three objects:
            anchor -- the encodings for the anchor data
            positive -- the encodings for the positive data (similar to anchor)
            negative -- the encodings for the negative data (different from anchor)
    Returns:
    loss -- real number, value of the loss
    """
    print('y_pred.shape = ',y_pred)
    
    total_lenght = y_pred.shape.as_list()[-1]
#     print('total_lenght=',  total_lenght)
#     total_lenght =12
    
    anchor = y_pred[:,0:int(total_lenght*1/3)]
    positive = y_pred[:,int(total_lenght*1/3):int(total_lenght*2/3)]
    negative = y_pred[:,int(total_lenght*2/3):int(total_lenght*3/3)]

    # distance between the anchor and the positive
    pos_dist = K.sum(K.square(anchor-positive),axis=1)

    # distance between the anchor and the negative
    neg_dist = K.sum(K.square(anchor-negative),axis=1)

    # compute loss
    basic_loss = pos_dist-neg_dist+alpha
    loss = K.maximum(basic_loss,0.0)
 
    return loss

def create_base_network_early(in_dims):
    """
    Base network to be shared.
    """
    model = Sequential()
    model.add(Conv2D(128,(7,7),padding='same',input_shape=(in_dims[0],in_dims[1],in_dims[2],),activation='relu',name='conv1'))
    model.add(MaxPooling2D((2,2),(2,2),padding='same',name='pool1'))
    model.add(Conv2D(256,(3,3),padding='same',activation='relu',name='conv2'))
    model.add(MaxPooling2D((2,2),(2,2),padding='same',name='pool2'))
    model.add(Flatten(name='flatten'))
    model.add(Dense(128,name='embeddings')) # No activation on final dense layer
    model.add(Lambda(lambda x: tf.math.l2_normalize(x, axis = 1)))
    # L2 normalize embeddings
    # model.add(Dense(600))
    
    return model

def create_base_network_late(in_dims):
    """
    Base network to be shared.
    """
    model = Sequential()
    model.add(Conv2D(128,(7,7),padding='same',input_shape=(in_dims[0],in_dims[1],in_dims[2],),activation='relu',name='conv1'))
    model.add(MaxPooling2D((2,2),(2,2),padding='same',name='pool1'))
    model.add(Conv2D(256,(5,5),padding='same',activation='relu',name='conv2'))
    model.add(MaxPooling2D((2,2),(2,2),padding='same',name='pool2'))
    model.add(Flatten(name='flatten'))
    model.add(Dense(256,name='embeddings')) # No activation on final dense layer
    # model.add(Lambda(lambda x: tf.math.l2_normalize(x, axis = 1))) # L2 normalize embeddings
    # model.add(Dense(600))
    
    return model

def CDML_model_train(X_train, method = 'early', n_epochs = 20):

    dim1 = X_train.shape[2]

    anchor_input = Input((dim1,1,1,), name='anchor_input')
    positive_input = Input((dim1,1,1,), name='positive_input')
    negative_input = Input((dim1,1,1,), name='negative_input')

    # Shared embedding layer for positive and negative items
    if method == 'early':
        Shared_DNN = create_base_network_early([dim1,1,1,])
    elif method == 'late':
        Shared_DNN = create_base_network_late([dim1,1,1,])

    encoded_anchor = Shared_DNN(anchor_input)
    encoded_positive = Shared_DNN(positive_input)
    encoded_negative = Shared_DNN(negative_input)

    merged_vector = concatenate([encoded_anchor, encoded_positive, encoded_negative], axis=-1, name='merged_layer')

    adam_optim = Adam(lr=0.0001, beta_1=0.9, beta_2=0.999)
    model = Model(inputs=[anchor_input,positive_input, negative_input], outputs=merged_vector)
    model.compile(loss=triplet_loss, optimizer=adam_optim)

    print(model.summary())

    # Optimize Triplet loss
    Anchor = X_train[:,0,:].reshape(-1,dim1,1,1)
    Positive = X_train[:,1,:].reshape(-1,dim1,1,1)
    Negative = X_train[:,2,:].reshape(-1,dim1,1,1)
    Anchor_test = X_test[:,0,:].reshape(-1,dim1,1,1)
    Positive_test = X_test[:,1,:].reshape(-1,dim1,1,1)
    Negative_test = X_test[:,2,:].reshape(-1,dim1,1,1)

    Y_dummy = np.empty((Anchor.shape[0],300))
    Y_dummy2 = np.empty((Anchor_test.shape[0],1))

    model.fit([Anchor,Positive,Negative], y=Y_dummy, 
        validation_data=([Anchor_test,Positive_test,Negative_test],Y_dummy2), batch_size=512, epochs=n_epochs)

    trained_model = Model(inputs=anchor_input, outputs=encoded_anchor)

    return trained_model

'''
    1. early fusion:
        - article_concat_wv

'''
# article_concat_wv.values
article_concat_wv = article_title_wv

X_train, X_test = generate_triplet(article_concat_wv.values, cowatched_list, zero_cowatched_dict, \
                                   ap_pairs=1000, an_pairs=1000,testsize=0.2)
print(X_train.shape, X_test.shape)


dim1 = X_train.shape[2]

trained_model_early = CDML_model_train(X_train, method = 'early', n_epochs = 20)


article_concat_wv_early_pred = trained_model_early.predict(article_concat_wv.values.reshape(-1, dim1, 1, 1))
# L2-norm
print(len(article_concat_wv_early_pred[0]), np.sqrt((article_concat_wv_early_pred[0]**2).sum()))

# Calculate similary matrix based on embedding features
sim_mat_CDML_early = 1 - pairwise_distances(article_concat_wv_early_pred, metric = 'cosine')
sim_mat_CDML_early[np.isnan(sim_mat_CDML_early)] = 0
print(sim_mat_CDML_early.shape)



'''
    3. content only:
        - article_title_wv

'''

sim_mat_content = 1 - pairwise_distances(article_title_wv, metric = 'cosine')
sim_mat_content[np.isnan(sim_mat_content)] = 0
# print(sim_mat_content[:5, :5])



'''
    4. TFIDF:

'''

articles = df_articles.copy()
articles['title'] = articles['title'].fillna("").astype('str')

tfidf = TfidfVectorizer(analyzer='word',ngram_range=(1, 2),min_df=0, stop_words='english')
tfidf_matrix = tfidf.fit_transform(articles['title'])
sim_mat_tfidf = linear_kernel(tfidf_matrix, tfidf_matrix)
del articles, tfidf_matrix


'''
    5.  NMF

'''
dat = df_clicks.copy()
dat['click'] = 1

R = dat.pivot(index = 'userId', columns='articleId', values = 'click').fillna(0)

reader = surprise.Reader(rating_scale=(0, 1))
data = surprise.Dataset.load_from_df(dat, reader)


nmf_alg = surprise.NMF(random_state = 123)

# n_factor: default = 50
nmf_output = nmf_alg.fit(data.build_full_trainset())
#print(nmf_output.qi.shape)

sim_mat_NMF = 1 - pairwise_distances(nmf_output.qi, metric = 'cosine')

#print(sim_mat_NMF.shape)
#print(sim_mat_NMF[:5, :5])

del dat, data, reader, nmf_output

'''
    6.  SVD

'''

dat = df_clicks.copy()
dat['click'] = 1

reader = surprise.Reader(rating_scale=(0, 1))
data = surprise.Dataset.load_from_df(dat, reader)

svd_alg = surprise.SVD(random_state = 123)

# n_factor: default = 100
svd_output = svd_alg.fit(data.build_full_trainset())

# output
# pu: The user factors (n_users, n_factors)
# qi: The item factors (n_items, n_factors)
# print(svd_output.pu.shape, svd_output.qi.shape)

# sim_mat_SVD = 1 - pairwise_distances(svd_output.qi, metric = 'correlation')
sim_mat_SVD = 1 - pairwise_distances(svd_output.qi, metric = 'cosine')

# print(sim_mat_SVD[:5, :5])

del dat, data, reader, svd_output


'''

    Article similary matrix:
        - sim_mat_CDML_early
        - sim_mat_CDML_late
        - sim_mat_content
        - sim_mat_tfidf
        - sim_mat_NMF
        - sim_mat_SVD
        - KNN 

'''

# Evaluation: 
#           - NDCG
#           - MAP


def cal_NDCG(rel_scores, threshold):
    if not threshold:
        # print('Original')
        DCG_k = sum([(2**i[1] - 1)/(np.log2((i[0]+1)+1)) \
                     for i in list(enumerate(rel_scores))])
        IDCG_k = sum([(2**i[1] - 1)/(np.log2((i[0]+1)+1)) \
                      for i in list(enumerate(sorted(rel_scores, reverse=True)))])
        NDCG_k = DCG_k/(IDCG_k+0.0001)
    else:
        # print(threshold)
        DCG_k = sum([(2**int(i[1] >= threshold) - 1)/(np.log2((i[0]+1)+1)) \
                 for i in list(enumerate(rel_scores))])
        IDCG_k = sum([(2**int(i[1] >= threshold) - 1)/(np.log2((i[0]+1)+1)) \
                      for i in list(enumerate(sorted(rel_scores, reverse=True)))])
        NDCG_k = DCG_k/(IDCG_k+0.0001)
    
    return NDCG_k


def cal_MAP(cowatched_mat_s, idx, rel_scores, threshold):    
    num_actual_rel = (cowatched_mat_s[idx] >= threshold).astype(int).sum()
    rel_scores_b = [int(i >= threshold) for i in rel_scores]

    precs = []
    recalls = []
    for indx, rec in enumerate(rel_scores_b):
        precs.append(sum(rel_scores_b[:indx+1])/(indx+1))
        recalls.append(sum(rel_scores_b[:indx+1])/(num_actual_rel+0.0001))

    delta_recalls = recalls - np.concatenate([[0], recalls[:(len(recalls)-1)]])
    # print(delta_recalls)

    MAP = sum(precs*delta_recalls)
    
    return MAP

# Function that get item recommendations
# method: 'standard', 'tripletNN'
def item_recommendations(articleId, item_corr, cowatched_mat_s, method, k):
    #print(method)

    idx = indices[articleId]
    target_category = articleIds[articleIds.articleId == articleId]['category'].values

    sim_scores_all = list(enumerate(item_corr[idx]))
    sim_scores_all.pop(idx)

    sim_scores_all = sorted(sim_scores_all, key = lambda x: x[1], reverse = True)

    # sim_scores = sim_scores[:k] # 
    article_indices = [i[0] for i in sim_scores_all]
    tmp_recommend = articleIds.iloc[article_indices].reset_index(drop = True)

    sim_scores = []
    kk = 1
    for i in range(tmp_recommend.shape[0]):
        if tmp_recommend['category'][i] != target_category and kk <= k:
            sim_scores.append(sim_scores_all[i])
            kk += 1
        elif tmp_recommend['category'][i] == target_category and kk <= k:
            continue
        elif kk > k:
            break

    del article_indices, tmp_recommend

    rel_scores = [cowatched_mat_s[idx, j] for j in [i[0] for i in sim_scores]]
    #print('# of cowatched users (rel_scores): '.format(rel_scores))

    ## (1) NDCG
    NDCG_k = cal_NDCG(rel_scores, threshold = None)
    #print('NDCG_orginal = {}'.format(NDCG_k))

    NDCG_k_b = cal_NDCG(rel_scores, threshold = 1)
    #print('NDCG_binary = {}'.format(NDCG_k_b))

    NDCG_k_b10 = cal_NDCG(rel_scores, threshold = 10)
    #print('NDCG_threshold10 = {}'.format(NDCG_k_b10))

    ## (2) MAP

    MAP_b = cal_MAP(cowatched_mat_s, idx, rel_scores, threshold = 1)
    #print('MAP_binary = {}'.format(MAP_b))

    MAP_b10 = cal_MAP(cowatched_mat_s, idx, rel_scores, threshold = 10)
    #print('MAP_threshold10 = {}'.format(MAP_b10))

    article_indices = [i[0] for i in sim_scores]
    tmp_recommend = articleIds.iloc[article_indices].reset_index(drop = True)

    return pd.concat([tmp_recommend, pd.DataFrame(rel_scores, columns=['rel_score'])], axis = 1), \
            NDCG_k, NDCG_k_b, NDCG_k_b10, MAP_b, MAP_b10

# evaluation with articleId_lists
def get_eval_results(articleId_lists, item_corr, cowatched_mat_s, method, k):
    print(method)
    
    df_metrics = pd.DataFrame(index = articleId_lists, columns = ['NDCG_orginal', 'NDCG_binary', 'NDCG_threshold10',
                                                                   'MAP_binary', 'MAP_threshold10'])

    df_popular_cnts = np.zeros((len(articleId_lists), k))
    df_rel_scores = np.zeros((len(articleId_lists), k))
    
    for i, target_id in enumerate(articleId_lists):
        tmp_results = item_recommendations(target_id, item_corr, cowatched_mat_s, method = method, k = k)
        df_popular_cnts[i] = tmp_results[0].cnts
        df_rel_scores[i] = tmp_results[0].rel_score
        
        # NDCG
        df_metrics.NDCG_orginal[target_id] = tmp_results[1]
        df_metrics.NDCG_binary[target_id] = tmp_results[2]
        df_metrics.NDCG_threshold10[target_id] = tmp_results[3]
        
        # MAP
        df_metrics.MAP_binary[target_id] = tmp_results[4]
        df_metrics.MAP_threshold10[target_id] = tmp_results[5]
            
    return df_metrics, df_popular_cnts, df_rel_scores


# Build a 1-dimensional array with articleIds
article_cnts = pd.DataFrame(df_clicks.groupby('articleId').size(), columns = ['cnts']).reset_index()

df_articles_cnts = pd.merge(df_articles, article_cnts, how = 'left', on = 'articleId') # articleId, title, body, cnts

articleIds = df_articles_cnts.copy()
indices = pd.Series(df_articles_cnts.index, index = df_articles_cnts['articleId'])


#------------------------------------------------------------------------------------------
# evaluation articleI
articleId_lists =  list(df_articles.sample(eval_num, random_state=nseed, replace = False)['articleId']) 

# print(articleId_lists[:10])

print('Evaluation with {} articles...'.format(eval_num))


#------------------------------------------------------------------------------------------
# 1. early fusion
# print('Evaluation with CDML early fusion model...')
# top-k article recommendations:

CDML_early_df_metrics, CDML_early_popular_cnts, CDML_early_rel_scores = get_eval_results(articleId_lists, 
                                                                                        item_corr = sim_mat_CDML_early,
                                                                                        cowatched_mat_s = cowatched_mat_s,
                                                                                        method = 'CDML with early fusion',
                                                                                        k = k)

#------------------------------------------------------------------------------------------
# 2. late fusion
# print('Evaluation with CDML late fusion model...')
# # top-k article recommendations:
# k = 4

# CDML_late_df_metrics, CDML_late_popular_cnts, CDML_late_rel_scores = get_eval_results(articleId_lists, 
#                                                                                         item_corr = sim_mat_CDML_late,
#                                                                                         cowatched_mat_s = cowatched_mat_s,
#                                                                                         method = 'CDML with late fusion',
#                                                                                         k = k)

#------------------------------------------------------------------------------------------
# 3. content only

content_df_metrics, content_popular_cnts, content_rel_scores = get_eval_results(articleId_lists, 
                                                                                item_corr = sim_mat_content,
                                                                                cowatched_mat_s = cowatched_mat_s,
                                                                                method = 'Content only',
                                                                                k = k)

#------------------------------------------------------------------------------------------
# 4. TF-IDF

TFIDF_df_metrics, TFIDF_popular_cnts, TFIDF_rel_scores = get_eval_results(articleId_lists, 
                                                                            item_corr = sim_mat_tfidf,
                                                                            cowatched_mat_s = cowatched_mat_s,
                                                                            method = 'TF-IDF',
                                                                            k = k)
#------------------------------------------------------------------------------------------
# 5. NMF

NMF_df_metrics, NMF_popular_cnts, NMF_rel_scores = get_eval_results(articleId_lists, 
                                                                    item_corr = sim_mat_NMF,
                                                                    cowatched_mat_s = cowatched_mat_s,
                                                                    method = 'NMF',
                                                                    k = k)

#------------------------------------------------------------------------------------------
# 6. SVD

SVD_df_metrics, SVD_popular_cnts, SVD_rel_scores = get_eval_results(articleId_lists, 
                                                                    item_corr = sim_mat_SVD,
                                                                    cowatched_mat_s = cowatched_mat_s,
                                                                    method = 'SVD',
                                                                    k = k)


##------------------------------------------------------------------------------------------
# Comparison results
comparison_results = pd.DataFrame([SVD_df_metrics.mean(axis = 0, skipna = True),
                                NMF_df_metrics.mean(axis = 0, skipna = True), 
#                                KNN_df_metrics.mean(axis = 0, skipna = True),
                                TFIDF_df_metrics.mean(axis = 0, skipna = True),
                                content_df_metrics.mean(axis = 0, skipna = True),
                                CDML_early_df_metrics.mean(axis = 0, skipna = True)], 
                                index=['SVD_mean', 'NMF_mean',
#                                       'KNN_mean',
                                       'TFIDF_mean', 'Content_mean', 'CDML_mean']) 
print('Comparison results for top-{} recommendaitons ...'.format(k))
print(comparison_results)


import pickle

rr = {
    'comparison_results': comparison_results, 
    'cowatched_max_num': cowatched_mat_s.max(),
    'cowatched_mean_num': cowatched_mat_s.mean(),
    'num_users': len(df_clicks.userId.unique()), 
    'num_articles': len(df_articles.articleId)
}


# Save zero_cowatched_dic
output_filename = 'Comparison_results_companydata_k{}_evalnum{}_subn{}.pkl'.format(k, eval_num, sub_n)

f = open(output_filename,"wb")
pickle.dump(rr, f)
f.close()

# comparison_results.to_csv(output_filename)


# Load data
# with open('rr.pkl'.format(sub_n), 'rb') as handle:
#     rr = pickle.load(handle)


print('Complete running recommendation models in {} seconds...'.format(round(time.time() - top_time,2)))








