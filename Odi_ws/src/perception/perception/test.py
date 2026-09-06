from google import genai

client = genai.Client(api_key="AQ.Ab8RN6LinihDTkvlW2M11VREjiLMUvZTVbXRMV7KmfmuAZArhA")

for model in client.models.list():
    print(model.name)