import os
import pickle
import tempfile
from collections import Counter

import numpy as np
from tqdm import tqdm

from utils import stream_from_file


class Batcher:
    TMP_DIR = tempfile.gettempdir()

    SEP = '\t'

    # Maximum password length. Passwords greater than this length will be discarded during the encoding phase.
    ENCODING_MAX_PASSWORD_LENGTH = 12

    # Maximum number of characters for encoding. By default, we use the 80 most frequent characters and
    # we bin the other ones in a OOV (out of vocabulary) group.
    ENCODING_MAX_SIZE_VOCAB = 80

    INPUTS_TARGETS_FILENAME = os.path.join(TMP_DIR, 'x_y.npz')

    OOV_CHAR = '？'
    PAD_CHAR = ' '

    def __init__(self, load=True):
        if not os.path.exists(self.TMP_DIR):
            os.makedirs(self.TMP_DIR)

        self.token_indices = os.path.join(self.TMP_DIR, 'token_indices.pkl')
        self.indices_token = os.path.join(self.TMP_DIR, 'indices_token.pkl')

        if load:
            try:
                self.chars, self.c_table = self.get_chars_and_ctable()
            except FileNotFoundError:
                raise Exception('Run first run_encoding.py to generate the required files.')

    @staticmethod
    def build(training_filename):
        print('Building vocabulary...')
        build_vocabulary(training_filename)
        print('Vectorization...')
        data_loader = LazyDataLoader(training_filename)
        _, _, training_records_count = data_loader.statistics()
        inputs = []
        targets = []
        print('Generating data...')
        for _ in tqdm(range(training_records_count), desc='Generating inputs and targets'):
            x_, y_ = data_loader.next()
            # Pad the data with spaces such that it is always MAXLEN.
            inputs.append(x_)
            targets.append(y_)

        np.savez_compressed(Batcher.INPUTS_TARGETS_FILENAME, inputs=inputs, targets=targets)

        print(f'Done... File is {Batcher.INPUTS_TARGETS_FILENAME}')

    @staticmethod
    def load():
        if not os.path.exists(Batcher.INPUTS_TARGETS_FILENAME):
            raise Exception('Please run the vectorization script before.')

        print('Loading data from prefetch...')
        data = np.load(Batcher.INPUTS_TARGETS_FILENAME)
        inputs = data['inputs']
        targets = data['targets']

        print('Data:')
        print(inputs.shape)
        print(targets.shape)
        return inputs, targets

    def chars_len(self):
        return len(self.chars)

    def get_indices_token(self):
        return pickle.load(open(self.indices_token, 'rb'))

    def get_token_indices(self):
        return pickle.load(open(self.token_indices, 'rb'))

    def get_vocab_size(self):
        return len(self.get_token_indices())

    def get_chars_and_ctable(self):
        chars = ''.join(list(self.get_token_indices().values()))
        ctable = CharacterTable(chars)
        return chars, ctable

    def write(self, vocabulary_sorted_list):
        token_indices = dict((c, i) for (c, i) in enumerate(vocabulary_sorted_list))
        indices_token = dict((i, c) for (c, i) in enumerate(vocabulary_sorted_list))
        assert len(token_indices) == len(indices_token)

        with open(self.token_indices, 'wb') as w:
            pickle.dump(obj=token_indices, file=w)

        with open(self.indices_token, 'wb') as w:
            pickle.dump(obj=indices_token, file=w)

        print(f'Done... File is {self.token_indices}.')
        print(f'Done... File is {self.indices_token}.')

    def decode(self, char, calc_argmax=True):
        return self.c_table.decode(char, calc_argmax)

    def encode(self, elt, num_rows=ENCODING_MAX_PASSWORD_LENGTH):
        return self.c_table.encode(elt, num_rows)


def discard_password(password):
    return len(password) > Batcher.ENCODING_MAX_PASSWORD_LENGTH or ' ' in password


class CharacterTable(object):
    """Given a set of characters:
    + Encode them to a one hot integer representation
    + Decode the one hot integer representation to their character output
    + Decode a vector of probabilities to their character output
    """

    def __init__(self, chars):
        """Initialize character table.
        # Arguments
            chars: Characters that can appear in the input.
        """
        self.chars = sorted(set(chars))
        self.char_indices = dict((c, i) for i, c in enumerate(self.chars))
        self.indices_char = dict((i, c) for i, c in enumerate(self.chars))

    def encode(self, C, num_rows):
        """One hot encode given string C.
        # Arguments
            num_rows: Number of rows in the returned one hot encoding. This is
                used to keep the # of rows for each data the same.
        """
        x = np.zeros((num_rows, len(self.chars)))
        for i in range(num_rows):
            try:
                c = C[i]
                if c not in self.char_indices:
                    x[i, self.char_indices['？']] = 1
                else:
                    x[i, self.char_indices[c]] = 1
            except IndexError:
                x[i, self.char_indices[' ']] = 1
        return x

    def decode(self, x, calc_argmax=True):
        if calc_argmax:
            x = x.argmax(axis=-1)
        return ''.join(self.indices_char[x] for x in x)


class colors:
    ok = '\033[92m'
    fail = '\033[91m'
    close = '\033[0m'


def build_vocabulary(training_filename):
    sed = Batcher(load=False)
    vocabulary = Counter()
    print('Reading file {}.'.format(training_filename))
    with open(training_filename, 'r', encoding='utf8', errors='ignore') as r:
        for s in tqdm(r.readlines(), desc='Build Vocabulary'):
            _, x, y = s.strip().split(Batcher.SEP)
            if discard_password(y) or discard_password(x):
                continue
            vocabulary += Counter(list(y + x))
    vocabulary_sorted_list = sorted(dict(vocabulary.most_common(sed.ENCODING_MAX_SIZE_VOCAB)).keys())

    print('Out of vocabulary (OOV) char is {}.'.format(sed.OOV_CHAR))
    print('Pad char is "{}".'.format(sed.PAD_CHAR))
    vocabulary_sorted_list.append(sed.OOV_CHAR)  # out of vocabulary.
    vocabulary_sorted_list.append(sed.PAD_CHAR)  # pad char.
    print('Vocabulary = ' + ' '.join(vocabulary_sorted_list))
    sed.write(vocabulary_sorted_list)


class LazyDataLoader:

    def __init__(self, training_filename):
        self.training_filename = training_filename
        self.stream = self.init_stream()

    def init_stream(self):
        return stream_from_file(self.training_filename, sep=Batcher.SEP)

    def next(self):
        try:
            return next(self.stream)
        except:
            self.stream = self.init_stream()
            return self.next()

    def statistics(self):
        max_len_value_x = 0
        max_len_value_y = 0
        num_lines = 0
        self.stream = self.init_stream()
        for x, y in self.stream:
            max_len_value_x = max(max_len_value_x, len(x))
            max_len_value_y = max(max_len_value_y, len(y))
            num_lines += 1

        print('max_len_value_x =', max_len_value_x)
        print('max_len_value_y =', max_len_value_y)
        print('num_lines =', num_lines)
        return max_len_value_x, max_len_value_y, num_lines
