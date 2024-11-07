from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoModel, AutoTokenizer
import torch, re
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from PyPDF2 import PdfReader

# Setup BERT model
model_name = "bert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModel.from_pretrained(model_name)
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)

# Ensure stopwords are available
nltk.download('stopwords')
nltk.download('punkt')
stop_words = set(stopwords.words("english"))

# Extract text from PDF
def extract_text_from_pdf(file_path):
    pdf_reader = PdfReader(file_path)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() or ""
    return text

def preprocess_text(text):
    text = text.lower()
    text = re.sub('[^a-zA-Z\s]', '', text)
    words = word_tokenize(text)
    return ' '.join(word for word in words if word not in stop_words)

def get_bert_embedding(text):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True).to(device)
    outputs = model(**inputs)
    embedding = outputs.last_hidden_state.mean(dim=1).detach().cpu().numpy()
    return embedding

def calculate_similarity(resume_text, jd_text):
    resume_embedding = get_bert_embedding(preprocess_text(resume_text))
    jd_embedding = get_bert_embedding(preprocess_text(jd_text))
    return cosine_similarity(resume_embedding, jd_embedding)[0][0]

# Read and process resume PDF
resume_text = extract_text_from_pdf("/Users/tufu1102/Downloads/16877897-HR.pdf")
jd_text = extract_text_from_pdf("/Users/tufu1102/Downloads/sample-job-description.pdf")
print(calculate_similarity(resume_text, jd_text))