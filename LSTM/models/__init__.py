"""
10 種 LSTM 模型
"""
from .m01_vanilla       import build as build_m01
from .m02_stacked       import build as build_m02
from .m03_bidirectional import build as build_m03
from .m04_attention     import build as build_m04
from .m05_cnn_lstm      import build as build_m05
from .m06_multifeature  import build as build_m06
from .m07_seq2seq       import build as build_m07
from .m08_mc_dropout    import build as build_m08
from .m09_technical     import build as build_m09

MODEL_BUILDERS = {
    "m01_vanilla":       build_m01,
    "m02_stacked":       build_m02,
    "m03_bidirectional": build_m03,
    "m04_attention":     build_m04,
    "m05_cnn_lstm":      build_m05,
    "m06_multifeature":  build_m06,
    "m07_seq2seq":       build_m07,
    "m08_mc_dropout":    build_m08,
    "m09_technical":     build_m09,
}
