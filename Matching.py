import spacy, fitz,io
from flask import  session,request
from database import mongo
from bson.objectid import ObjectId
from MediaWiki import get_search_results
from test import calculate_similarity

resumeFetchedData = mongo.db.resumeFetchedData
JOBS = mongo.db.JOBS


###Spacy model
print("Loading Jd Parser model...")
jd_model = spacy.load('assets/JdModel/output/model-best')
print("Jd Parser model loaded")




def Matching():
    job_id = request.form['job_id']
    
    # Fetch job description data
    jd_data = JOBS.find_one({"_id": ObjectId(job_id)}, {"FileData": 1})["FileData"]
    with io.BytesIO(jd_data) as data:
        doc = fitz.open(stream=data)
        text_of_jd = ""
        for page in doc:
            text_of_jd += str(page.get_text())

    # Fetch resume data for the user
    user_id = ObjectId(session['user_id'])
    resume_data = resumeFetchedData.find_one({"UserId": user_id})

    # Extract the text of the resume (already stored as ResumeData)
    text_of_resume = resume_data.get('ResumeData', "")

    # Calculate cosine similarity between resume and job description
    match_percentage = calculate_similarity(text_of_resume, text_of_jd)
    
    return float(match_percentage) * 100
