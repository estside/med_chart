from django import forms

class ChatForm(forms.Form):
    text_input = forms.CharField(required=False, widget=forms.Textarea)
    audio_input = forms.FileField(required=False)
    image_input = forms.ImageField(required=False)
