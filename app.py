from flask import Flask, render_template, url_for, request, session, redirect, abort, jsonify
from database import mongo
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os, re, spacy, fitz, pathlib, requests, json, google.auth.transport.requests
from bson.objectid import ObjectId
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from pip._vendor import cachecontrol
from PyPDF2 import PdfReader
import google.generativeai as genai

# Helper functions
def allowedExtension(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ['docx', 'pdf']

def allowedExtensionPdf(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ['pdf']

app = Flask(__name__)
app.secret_key = "Resume_screening"
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
GOOGLE_CLIENT_ID = "452004688987-hkglohcapsk6v1q1q79f3t4cb95dfa05.apps.googleusercontent.com"
client_secrets_file = os.path.join(pathlib.Path(__file__).parent, "client_secret.json")
flow = Flow.from_client_secrets_file(
    client_secrets_file=client_secrets_file,
    scopes=["https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/userinfo.email", "openid"],
    redirect_uri="http://127.0.0.1:5000/callback"
)

UPLOAD_FOLDER = 'static/uploaded_resumes'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MONGO_URI'] = 'mongodb+srv://admin:admin@cluster0.jywcp.mongodb.net/ResumeParser'

mongo.init_app(app)
resumeFetchedData = mongo.db.resumeFetchedData
Applied_EMP = mongo.db.Applied_EMP
IRS_USERS = mongo.db.IRS_USERS
JOBS = mongo.db.JOBS

resume_uploaded = False

# Blueprint for Job Posting
from Job_post import job_post
app.register_blueprint(job_post, url_prefix="/HR1")

### Spacy model loading
print("Loading Resume Parser model...")
nlp = spacy.load('assets/ResumeModel/output/model-best')
print("Resume Parser model loaded")

# Routes
@app.route('/')
def index():
    return render_template("index.html")

# --- Login & Signup Methods ---
@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/signup')
def signup():
    return render_template('signup.html')

@app.route('/form_login', methods=["POST"])
def form_login():
    email = str(request.form.get('email'))
    password = str(request.form.get('password'))
    result = IRS_USERS.find_one({"Email": email})

    # Check if user exists
    if result:
        if result['Google_id'] is not None:
            # User signed up with Google; handle as per your logic (e.g., inform them)
            return render_template("login.html", errMsg="This email is linked to a Google account. Please log in using Google.")
        
        # If a password is set, verify it
        if check_password_hash(result['Password'], password):
            session['user_id'] = str(result['_id'])
            session['user_name'] = result['Name']
            return redirect("/emp")
        else:
            return render_template("login.html", errMsg="Invalid email or password")
    else:
        return render_template("login.html", errMsg="Invalid email or password")

@app.route('/form_signup', methods=["POST"])
def form_signup():
    name = str(request.form.get('name'))
    email = str(request.form.get('email'))
    password = str(request.form.get('password'))

    # Check for existing user with the same email
    existing_user = IRS_USERS.find_one({"Email": email})
    if existing_user:
        return render_template("signup.html", errMsg="Email already exists. Please use a different email.")

    # Hash the password
    hashed_password = generate_password_hash(password)

    # Insert new user
    result = IRS_USERS.insert_one({
        "Name": name,
        "Email": email,
        "Password": hashed_password,  # Store hashed password
        "Google_id": None  # Set to None for form signups
    })
    if result:
        return render_template("index.html", successMsg="User created successfully!")
    else:
        return render_template("signup.html", errMsg="User creation failed. Try again.")

# --- Google Login & Signup Methods ---
@app.route('/google_login')
def google_login():
    authorization_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(authorization_url)

@app.route('/google_signup')
def google_signup():
    authorization_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    flow.fetch_token(authorization_response=request.url)

    if not session["state"] == request.args["state"]:
        abort(500)  # State does not match!

    credentials = flow.credentials
    request_session = requests.session()
    cached_session = cachecontrol.CacheControl(request_session)
    token_request = google.auth.transport.requests.Request(session=cached_session)

    id_info = google.oauth2.id_token.verify_oauth2_token(
        id_token=credentials._id_token,
        request=token_request,
        audience=GOOGLE_CLIENT_ID
    )

    email = id_info.get("email")
    name = id_info.get("name")
    google_id = id_info.get("sub")

    # Check if user already exists
    result = IRS_USERS.find_one({"Email": email})

    if result is None:
        # Create a new user only if they do not exist
        session['user_id'] = str(IRS_USERS.insert_one({
            "Name": name,
            "Email": email,
            "Password": None,  # Set to None for Google signups
            "Google_id": google_id  # Store Google ID
        }).inserted_id)
        session['user_name'] = name
    else:
        # Check if Google_id is None, meaning the user signed up via form
        if result['Google_id'] is None:
            # Link the Google account to the existing user
            IRS_USERS.update_one({"Email": email}, {"$set": {"Google_id": google_id}})
        
        session['user_id'] = str(result['_id'])
        session['user_name'] = result['Name']

    return redirect("/emp")

# --- Employee Dashboard ---
@app.route('/emp')
def emp():
    if 'user_id' in session and 'user_name' in session:
        return render_template("EmployeeDashboard.html")
    else:
        return render_template("index.html", errMsg="Login first")

@app.route("/logout")
def logout():
    session.pop('user_id',None)
    session.pop('user_name',None)
    return redirect(url_for("index"))

@app.route('/HR_Homepage', methods=['GET', 'POST'])
def HR_Homepage():
    return render_template("CompanyDashboard.html")

HR_CREDENTIALS = {
    "admin1": "password1",
    "admin2": "password2",
    "hrmanager": "securepass123"
}

@app.route('/HR', methods=['GET', 'POST'])
def HR():
    if request.method == 'POST':
        # Get the username and password from the form
        username = request.form['username']
        password = request.form['password']

        # Validate the HR credentials
        if username in HR_CREDENTIALS and HR_CREDENTIALS[username] == password:
            # Render the dashboard if credentials are correct
            return render_template("CompanyDashboard.html")
        else:
            # Return an error message if validation fails
            message = "Invalid username or password. Try again!"
            return render_template('form.html', message=message)
    else:
        # Render the form template
        return render_template('form.html')
    


@app.route('/test')
def test():
    return "Connection Successful"




@app.route("/uploadResume", methods=['POST'])
def uploadResume():
    if 'user_id' in session and 'user_name' in session:
        try:
            file = request.files['resume']
            filename = secure_filename(file.filename)
            # print("Extension:",file.filename.rsplit('.',1)[1].lower())
            if file and allowedExtension(file.filename):
                temp = resumeFetchedData.find_one({"UserId":ObjectId(session['user_id'])},{"ResumeTitle":1})

                if temp == None:
                    print("HELLO")
                else:
                    print("hello")
                    resumeFetchedData.delete_one({"UserId":ObjectId(session['user_id'])})
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'],temp['ResumeTitle']))
                file.save(os.path.join(app.config['UPLOAD_FOLDER'],filename))
                print("Resume Uploaded")
                
                
                fname = "static/uploaded_resumes/"+filename
                print(fname)
                doc = fitz.open(fname)
                print("Resume taken as input")

                text_of_resume = " "
                for page in doc:
                    text_of_resume = text_of_resume + str(page.get_text())

                label_list=[]
                text_list = []
                dic = {}
                
                doc = nlp(text_of_resume)
                for ent in doc.ents:
                    label_list.append(ent.label_)
                    text_list.append(ent.text)
                
                print("Model work done")

                for i in range(len(label_list)):
                    if label_list[i] in dic:
                        # if the key already exists, append the new value to the list of values
                        dic[label_list[i]].append(text_list[i])
                    else:
                        # if the key does not exist, create a new key-value pair
                        dic[label_list[i]] = [text_list[i]]
                
                print(dic)
                resume_data_annotated = ''
                for key, value in dic.items():
                    for val in value:
                        resume_data_annotated += val + " "
               
                resume_name = dic.get('NAME')
                if resume_name is not None:
                    value_name = resume_name[0]
                else:
                    value_name = None

                resume_linkedin = dic.get('LINKEDIN LINK')
                if resume_linkedin is not None:
                    value_linkedin = resume_linkedin[0]
                    value_linkedin = re.sub('\n', '',value_linkedin)
                else:
                    value_linkedin= None


                resume_skills = dic.get('SKILLS')
                if resume_skills is not None:                  
                    value_skills = resume_skills
                else:
                    value_skills = None

                resume_certificate = dic.get('CERTIFICATION')
                if resume_certificate is not None:
                    value_certificate = resume_certificate
                else:
                    value_certificate=None

                resume_workedAs = dic.get('WORKED AS')
                if resume_workedAs is not None:
                    value_workedAs = resume_workedAs
                else:
                    value_workedAs = None
            

                resume_experience = dic.get('YEARS OF EXPERIENCE', ["1 years"])
                if resume_experience is not None:
                    value_experience = resume_experience
                else:
                    value_experience = None
               
                
                result = None               
                result = resumeFetchedData.insert_one({"UserId":ObjectId(session['user_id']),"Name":value_name,"LINKEDIN LINK": resume_linkedin,"SKILLS": value_skills,"CERTIFICATION": value_certificate,"WORKED AS":value_workedAs,"YEARS OF EXPERIENCE":value_experience,"Appear":0,"ResumeTitle":filename,"ResumeAnnotatedData":resume_data_annotated,"ResumeData":text_of_resume})                
                
                if result == None:
                    return render_template("EmployeeDashboard.html",errorMsg="Problem in Resume Data Storage")  
                else:
                    return render_template("EmployeeDashboard.html",successMsg="Resume Screen Successfully!!")
            else:
                return render_template("EmployeeDashboard.html",errorMsg="Document Type Not Allowed")
        except:
            print("Exception Occured")
    else:
        return render_template("index.html", errMsg="Login First")


@app.route('/viewdetails', methods=['POST', 'GET'])
def viewdetails():      
    employee_id = request.form['employee_id']     
    result = resumeFetchedData.find({"UserId":ObjectId(employee_id)})     
    dt=result[0]
    name_resume=dt['Name']
    if name_resume is not None:
        name = name_resume
    else:
        name = None

    linkedin_link=dt['LINKEDIN LINK']
    if name_resume is not None:
        name = name_resume
    else:
        name = None

    skill_resume=dt['SKILLS']
    if skill_resume is not None:
        skills = skill_resume
    else:
        skills = None

    certificate_resume=dt['CERTIFICATION']
    if certificate_resume is not None:
        certificate = certificate_resume
    else:
        certificate = None

    return jsonify({'name':name,'linkedin_link':linkedin_link,'skills':skills,'certificate':certificate})


@app.route("/empSearch",methods=['POST'])
def empSearch():
    if request.method == 'POST':
        category = str(request.form.get('category'))
        print(category)
        
        TopEmployeers = None
        job_ids = []
        job_cursor = JOBS.find({"Job_Profile": category},{"_id": 1})
        for job in job_cursor:
            job_ids.append(job['_id'])

        TopEmployeers = Applied_EMP.find({"job_id": {"$in": job_ids}},{"user_id": 1, "Matching_percentage": 1}).sort([("Matching_percentage", -1)])
        # print(TopEmployeers)
        # print(type(TopEmployeers))
        if TopEmployeers == None:
            return render_template("CompanyDashboard.html",errorMsg="Problem in Category Fetched")
        else:
            selectedResumes={}
            cnt = 0

            for i in TopEmployeers:
                se=IRS_USERS.find_one({"_id":ObjectId(i['user_id'])},{"Name":1,"Email":1,"_id":1})
                selectedResumes[cnt] = {"Name":se['Name'],"Email":se['Email'],"_id":se['_id']}
                se = None
                cnt += 1
            print("len", len(selectedResumes))
            return render_template("CompanyDashboard.html",len = len(selectedResumes), data = selectedResumes)

# Configure the Gemini API Key
genai.configure(api_key="AIzaSyDtRd1yjaLht6l0I3pAk2YZQyNbMgMQkZA")

# Route to render the Resume Parser page
@app.route('/resume-parser', methods=['GET', 'POST'])
def resume_parser():
    ai_response = None
    
    if request.method == 'POST':
        # Check if a file is uploaded
        uploaded_file = request.files.get('resume')
        print(f'Uploaded file: {uploaded_file}')  # Debugging line
        
        if uploaded_file and uploaded_file.filename.endswith('.pdf'):
            # Parse the PDF file
            pdf_reader = PdfReader(uploaded_file)
            resume_text = ""
            for page in pdf_reader.pages:
                resume_text += page.extract_text()

            # Call the Gemini API to process the extracted resume text
            prompt = f"""
            You are a highly intelligent AI designed to extract key details from resumes and provide insights for job matching. Based on the following resume text, please do the following:

            1. Extract the following details from the resume:
            - Full Name
            - Contact Information (Email, Phone, LinkedIn)
            - Address (if available)
            - Skills
            - Job Titles and Work History (Company Names and Durations)
            - Educational Background
            - Relevant Certifications (if any)
            - Any additional relevant information like languages or special projects

            2. Based on the extracted details, suggest 3-5 job roles that best match the candidate’s profile.

            3. Provide an ATS (Applicant Tracking System) score (out of 100) to indicate how well this resume will perform when submitted to an ATS.

            4. Give personalized tips for improving the resume’s ATS score, including any missing keywords, formatting issues, or areas that could be emphasized.

            Resume Text:
            {resume_text}
            """
        

            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            
            parsed_data = resume_text
            ai_response = response.text
    
    return render_template('resume_parser.html', ai_response=ai_response)



if __name__=="__main__":
    app.run(debug=True)