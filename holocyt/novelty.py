"""Определение выхода за пределы обученного.

Зачем это нужно. Классификатор состояния обучен на определённом наборе
клеток. Встретив клетки, не похожие ни на что из обучения, модель
градиентного бустинга всё равно выдаст какой-нибудь класс — причём
уверенно. Так и вышло при первом прогоне на реальных снимках M4:
треть распластанных мигрирующих клеток здоровой культуры была объявлена
некрозом, потому что по заложенным в обучение признакам (большая
площадь, малый сдвиг фазы, изрезанный контур) они на некроз похожи.

Правильное поведение программы в такой ситуации — не угадывать, а
сказать: «эти клетки не похожи на те, на которых я обучена, состояние
определить не берусь». Измерения, которые от обучения не зависят —
счёт, площадь, конфлюентность, сухая масса, — при этом остаются в силе
и выдаются как обычно.

Реализация: расстояние Махаланобиса до обучающего распределения, с
оценкой ковариации методом Ледуа — Вольфа (сжатие к диагонали, иначе
при 27 признаках матрица плохо обусловлена). Порог калибруется на
обучающей выборке.

Выбор метода сделан по измерению, а не по вкусу. На отложенной
синтетике и на реальных снимках M4 доля отвергнутых составила:

    изолирующий лес                2,0 %  /  14,0 %
    Махаланобис (Ледуа — Вольф)    2,3 %  /  45,9 %
    поквантильная проверка         5,9 %  /  50,2 %

Изолирующий лес не годится: одиночный сильно сдвинутый признак
растворяется среди двадцати семи. Махаланобис учитывает ковариацию и
ловит именно совместный сдвиг.
"""

import numpy as np
from sklearn.covariance import LedoitWolf
from sklearn.preprocessing import RobustScaler

# Доля обучающей выборки, которую допустимо считать незнакомой.
DEFAULT_CONTAMINATION = 0.02

# Доля незнакомых клеток в кадре, выше которой состав популяции
# не сообщается вовсе.
UNRELIABLE_FRACTION = 0.30

UNDETERMINED = "unknown"


class NoveltyDetector:
    """Отвечает на вопрос «похожа ли эта клетка на то, чему модель училась»."""

    def __init__(self, contamination=DEFAULT_CONTAMINATION, random_state=3):
        self.contamination = contamination
        self.random_state = random_state
        self.scaler = None
        self.cov = None
        self.threshold = None
        self.feature_names = None
        self.n_train = 0

    def fit(self, X, feature_names=None):
        X = np.nan_to_num(np.asarray(X, dtype=np.float64), nan=0.0,
                          posinf=0.0, neginf=0.0)
        self.feature_names = list(feature_names) if feature_names else None
        self.n_train = len(X)

        # Робастная шкала: морфометрия даёт тяжёлые хвосты, и обычная
        # стандартизация по среднему и СКО на них разъезжается.
        self.scaler = RobustScaler().fit(X)
        Z = self.scaler.transform(X)

        self.cov = LedoitWolf().fit(Z)
        d = self.cov.mahalanobis(Z)
        # Порог — верхний квантиль расстояний на обучающей выборке.
        self.threshold = float(np.quantile(d, 1.0 - self.contamination))
        return self

    def score(self, X):
        """Расстояние Махаланобиса до обучающего распределения.

        Чем БОЛЬШЕ, тем дальше клетка от того, чему модель училась.
        """
        X = np.nan_to_num(np.asarray(X, dtype=np.float64), nan=0.0,
                          posinf=0.0, neginf=0.0)
        return self.cov.mahalanobis(self.scaler.transform(X))

    def is_known(self, X):
        """Булев массив: похожа ли клетка на обучающие данные."""
        return self.score(X) <= self.threshold


def reliability(states, known):
    """Сводка о том, насколько можно доверять определению состояний.

    states — метки состояний, known — булев массив «в пределах обученного».
    """
    n = len(states)
    if n == 0:
        return {"n": 0, "n_known": 0, "unknown_fraction": float("nan"),
                "reliable": False,
                "note": "клеток не найдено"}
    n_known = int(np.count_nonzero(known))
    frac = 1.0 - n_known / n
    reliable = frac <= UNRELIABLE_FRACTION
    if reliable:
        note = ("состав популяции определён: клетки попадают в область, "
                "на которой модель обучена")
    else:
        note = (f"состав популяции НЕ определён: {100 * frac:.0f} % клеток "
                f"не похожи на обучающие данные. Требуется дообучение "
                f"модели на этой клеточной линии. Счёт клеток, площадь, "
                f"конфлюентность и сухая масса от этого не зависят и "
                f"приведены как обычно")
    return {"n": n, "n_known": n_known, "unknown_fraction": frac,
            "reliable": bool(reliable), "note": note}
