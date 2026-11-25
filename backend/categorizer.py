"""Small multinomial Naive Bayes classifier; corrected transactions become examples.

The starter corpus is intentionally small. Scores are model scores, not calibrated
accuracy estimates. Unknown descriptions are left as Other for user review.
"""
import math
import re
from collections import Counter, defaultdict

CORPUS = {
    'Food & drinks': ['coffee cafe latte espresso brown coffee', 'restaurant dinner lunch breakfast noodles pizza', 'អាហារ បាយ កាហ្វេ ភោជនីយដ្ឋាន'],
    'Groceries': ['supermarket grocery vegetables fruit market rice eggs', 'lucky supermarket aeon grocery fresh mart', 'ផ្សារ បន្លែ ផ្លែឈើ'],
    'Transport': ['grab passapp tuktuk taxi bus petrol fuel parking', 'transport motorcycle gasoline ride', 'សាំង កង់ ម៉ូតូ តាក់ស៊ី'],
    'Shopping': ['clothes shoes clothing shopping electronics phone', 'zando uniqlo bookshop gift household', 'សម្លៀកបំពាក់ ស្បែកជើង'],
    'Bills & utilities': ['rent electricity water internet phone bill utilities', 'edc ezecom smart cellcard metfone', 'ទឹក ភ្លើង អ៊ីនធឺណិត'],
    'Entertainment': ['cinema movie netflix spotify gaming concert', 'legend major cineplex music karaoke', 'ភាពយន្ត កម្សាន្ត'],
    'Health': ['pharmacy medicine doctor hospital dentist clinic', 'health medical dental treatment', 'ពេទ្យ ថ្នាំ សុខភាព'],
    'Education': ['school tuition course university learning class', 'education training lessons textbook', 'សាលា សៀវភៅ សិក្សា'],
    'Travel': ['hotel flight holiday vacation airline resort', 'travel booking airbnb tourism airport', 'សណ្ឋាគារ ដំណើរ យន្តហោះ'],
}


def tokens(text):
    words = re.findall(r'[a-z0-9]+|[\u1780-\u17ff]+', text.lower())
    return [token for word in words for token in ([word] if word.isascii() else [word[i:i+3] for i in range(max(1, len(word)-2))])]


def suggest(description, examples=()):
    counts, documents = defaultdict(Counter), Counter()
    for category, texts in CORPUS.items():
        for text in texts:
            counts[category].update(tokens(text))
            documents[category] += 1
    for text, category in examples:
        if category in CORPUS:
            counts[category].update(tokens(text))
            documents[category] += 1
    vocabulary = set().union(*(set(c) for c in counts.values()))
    features = [t for t in tokens(description) if t in vocabulary]
    if not features:
        return {'category': 'Other', 'score': 0, 'model': 'Multinomial Naive Bayes'}
    scores = {}
    for category, frequency in counts.items():
        scores[category] = math.log(documents[category] / sum(documents.values())) + sum(
            math.log((frequency[t] + 1) / (frequency.total() + len(vocabulary))) for t in features
        )
    best = max(scores, key=scores.get)
    normalizer = sum(math.exp(v - scores[best]) for v in scores.values())
    return {'category': best, 'score': round(1 / normalizer, 3), 'model': 'Multinomial Naive Bayes'}
