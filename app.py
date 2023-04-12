import os
import openpyxl
import pandas as pd
import fnmatch
from xls2xlsx import XLS2XLSX
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from datetime import datetime
from flask_bootstrap import Bootstrap
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from PIL import Image

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

# Endpoint to render the file upload form
@app.route('/')
def index():
        return render_template('index.html')


# Endpoint to handle the file upload
@app.route('/upload', methods=['POST'])
def upload_files():
        if 'file1' not in request.files or 'file2' not in request.files:
                return 'Both Excel files must be provided', 400

        file1 = request.files['file1']
        file2 = request.files['file2']

        if file1.filename == '' or file2.filename == '':
                return 'Both Excel files must have a valid name', 400

        # Save the files to the server
        file1_path = os.path.join(app.config['UPLOAD_FOLDER'], file1.filename)
        file2_path = os.path.join(app.config['UPLOAD_FOLDER'], file2.filename)
        file1.save(file1_path)
        file2.save(file2_path)

        # Collect the additional form fields
        calls_to_pull = request.form['calls_to_pull']
        call_distribution_type = request.form['call_distribution_type']
        preferred_nature_codes = request.form['preferred_nature_codes']
        excluded_nature_codes = request.form['excluded_nature_codes']
        excluded_dispositions = request.form['excluded_dispositions']

        # Redirect to the processing endpoint
        return redirect(url_for('process_files',
                                                        file1=file1.filename,
                                                        file2=file2.filename,
                                                        calls_to_pull=calls_to_pull,
                                                        call_distribution_type=call_distribution_type,
                                                        preferred_nature_codes=preferred_nature_codes,
                                                        excluded_nature_codes=excluded_nature_codes,
                                                        excluded_dispositions=excluded_dispositions))


@app.route('/process_files')
def process_files():
        Short_Report = request.args.get('file1')
        Ani_Ali_Report = request.args.get('file2')
        Calls_Per_Day = int(request.args.get('calls_to_pull'))
        Call_Distribution_Type = request.args.get('call_distribution_type')
        Preferred_Natures = request.args.get('preferred_nature_codes')
        Excluded_Natures = request.args.get('excluded_nature_codes')
        Excluded_Dispositions = request.args.get('excluded_dispositions')

        #file 1 = Short_Report
        #file 2 = Ani_Ali_Report

        file1_path = os.path.join(app.config['UPLOAD_FOLDER'], Short_Report)
        file2_path = os.path.join(app.config['UPLOAD_FOLDER'], Ani_Ali_Report)

        #   CLEAN UP DOCUMENTS
        def convert_xls_to_xlsx(filename, newfile):
                x2x = XLS2XLSX(f"uploads/{filename}")
                wb = x2x.to_xlsx(newfile)
                return newfile
        def delete_rows_in_excel(file_name, start_row, num_rows):
                #load wrkbook
                workbook = openpyxl.load_workbook(file_name)

                #get active sheet
                sheet = workbook.active

                #delete specified rows
                sheet.delete_rows(start_row, num_rows)

                #save modified wrkbook
                workbook.save(file_name)

        Ani_Ali_Report = convert_xls_to_xlsx(Ani_Ali_Report, "temp/aniali.xlsx")
        Short_Report = convert_xls_to_xlsx(Short_Report, "temp/shortreport.xlsx")
        delete_rows_in_excel(Ani_Ali_Report, 1, 7)
        delete_rows_in_excel(Short_Report, 1, 7)


        #	EXTRACT DATA
        anialidf = pd.read_excel(Ani_Ali_Report, dtype={"Phone #": str, "Inci Id": str, "Console": str})
        shortreportdf = pd.read_excel(Short_Report)


        #	CLEAN UP DATA
        #Remove hyphens in shortreport event id
        shortreportdf['Event ID'] = shortreportdf['Event ID'].astype(str).apply(lambda x: x.replace('-', ''))
        #Rename aniali inci id to Event ID
        anialidf = anialidf.rename(columns={'Inci Id': 'Event ID'})

        #	MERGE DATA
        date_format = "%m/%d/%Y %H:%M:%S"
        merged_df = anialidf.merge(shortreportdf, on="Event ID", how="inner")
        merged_df['Process Time'] = pd.to_datetime(merged_df['Process Time'], format=date_format)

        #	DROP IRRELEVANT COLUMNS
        selected_columns = ['Event ID', 'Nature', 'Disp.', 'Phone #', 'Customer', 'Location', 'City', 'Process Time', 'Classser']
        merged_df = merged_df[selected_columns]

        #	APPLY FILTERS
        Preferred_Natures_List = Preferred_Natures.split(',')
        Excluded_Natures_List = Excluded_Natures.split(',')
        Excluded_Dispositions_List = Excluded_Dispositions.split(',')

        filtered_df = pd.DataFrame(columns=merged_df.columns)

        for item in Preferred_Natures_List:
                for index, row in merged_df.iterrows():
                        if row['Nature'] == item:
                                # Append the row to the filtered_df using pandas.concat
                                filtered_df = pd.concat([filtered_df, row.to_frame().T], ignore_index=True)

        for index, row in merged_df.iterrows():
                if (row['Disp.'] not in Excluded_Dispositions_List and
                        row['Nature'] not in Excluded_Natures_List and
                        row['Event ID'] not in filtered_df['Event ID'].values):
                        # Append row to filtered_df using pandas.concat
                        filtered_df = pd.concat([filtered_df, row.to_frame().T], ignore_index=True)

        filtered_df = filtered_df[(filtered_df['Classser'] == 'WRLS') | (filtered_df['Classser'] == 'WPH2')]


        #	APPLY CALL DISTRIBUTION TYPE
        night_shift_df = pd.DataFrame(columns=filtered_df.columns)
        day_shift_df = pd.DataFrame(columns=filtered_df.columns)

        for index, row in filtered_df.iterrows():
                # Extract the hour from the "Process Time" datetime object
                process_hour = row['Process Time'].hour

                if process_hour < 6 or process_hour >= 18:
                        night_shift_df = pd.concat([night_shift_df, row.to_frame().T], ignore_index=True)
                else:
                        day_shift_df = pd.concat([day_shift_df, row.to_frame().T], ignore_index=True)

        # Assuming filtered_df, Call_Distribution_Type, and Calls_Per_Day are already defined
        present_df = pd.DataFrame(columns=filtered_df.columns)


        if Call_Distribution_Type == "default":
                # Extract unique dates from the "Process Time" column
                unique_dates = pd.to_datetime(filtered_df['Process Time']).dt.date.unique()

                # Print the number of unique dates
                print(f"Total unique dates: {len(unique_dates)}")

                for date in unique_dates:
                        # Filter the rows with the same date
                        same_date_rows = filtered_df[pd.to_datetime(filtered_df['Process Time']).dt.date == date]

                        # Reset the index to avoid errors when concatenating
                        same_date_rows.reset_index(drop=True, inplace=True)

                        # Iterate over the rows Calls_Per_Day times, or up to the length of same_date_rows
                        for i in range(min(Calls_Per_Day, len(same_date_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_rows.loc[[i]]], ignore_index=True)
        elif Call_Distribution_Type == "even_split":
                # Extract unique dates from the "Process Time" column
                unique_dates = pd.to_datetime(filtered_df['Process Time']).dt.date.unique()
                Day_Amount = Calls_Per_Day // 2
                Night_Amount = Calls_Per_Day - Day_Amount

                # Print the number of unique dates
                print(f"Total unique dates: {len(unique_dates)}")

                for date in unique_dates:
                        # Filter the rows with the same date in day_shift_df
                        same_date_day_rows = day_shift_df[pd.to_datetime(day_shift_df['Process Time']).dt.date == date]
                        # Reset the index to avoid errors when concatenating
                        same_date_day_rows.reset_index(drop=True, inplace=True)

                        # Filter the rows with the same date in night_shift_df
                        same_date_night_rows = night_shift_df[pd.to_datetime(night_shift_df['Process Time']).dt.date == date]
                        # Reset the index to avoid errors when concatenating
                        same_date_night_rows.reset_index(drop=True, inplace=True)

                        # Iterate over the rows Day_Amount times, or up to the length of same_date_day_rows
                        for i in range(min(Day_Amount, len(same_date_day_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_day_rows.loc[[i]]], ignore_index=True)

                        # Iterate over the rows Night_Amount times, or up to the length of same_date_night_rows
                        for i in range(min(Night_Amount, len(same_date_night_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_night_rows.loc[[i]]], ignore_index=True)
        elif Call_Distribution_Type == "day_shift":
                # Extract unique dates from the "Process Time" column
                unique_dates = pd.to_datetime(filtered_df['Process Time']).dt.date.unique()
                Day_Amount = Calls_Per_Day

                # Print the number of unique dates
                print(f"Total unique dates: {len(unique_dates)}")

                for date in unique_dates:
                        # Filter the rows with the same date in day_shift_df
                        same_date_day_rows = day_shift_df[pd.to_datetime(day_shift_df['Process Time']).dt.date == date]
                        # Reset the index to avoid errors when concatenating
                        same_date_day_rows.reset_index(drop=True, inplace=True)

                        # Iterate over the rows Day_Amount times, or up to the length of same_date_day_rows
                        for i in range(min(Day_Amount, len(same_date_day_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_day_rows.loc[[i]]], ignore_index=True)
        elif Call_Distribution_Type == "night_shift":
                # Extract unique dates from the "Process Time" column
                unique_dates = pd.to_datetime(filtered_df['Process Time']).dt.date.unique()
                Night_Amount = Calls_Per_Day

                # Print the number of unique dates
                print(f"Total unique dates: {len(unique_dates)}")

                for date in unique_dates:
                        # Filter the rows with the same date in day_shift_df
                        same_date_night_rows = night_shift_df[pd.to_datetime(day_shift_df['Process Time']).dt.date == date]
                        # Reset the index to avoid errors when concatenating
                        same_date_night_rows.reset_index(drop=True, inplace=True)

                        # Iterate over the rows Day_Amount times, or up to the length of same_date_day_rows
                        for i in range(min(Night_Amount, len(same_date_night_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_night_rows.loc[[i]]], ignore_index=True)
        elif Call_Distribution_Type == "based_on_call_volume":
                # Extract unique dates from the "Process Time" column
                unique_dates = pd.to_datetime(filtered_df['Process Time']).dt.date.unique()

                # Print the number of unique dates
                print(f"Total unique dates: {len(unique_dates)}")

                for date in unique_dates:
                        # Filter the rows with the same date in day_shift_df
                        same_date_day_rows = day_shift_df[pd.to_datetime(day_shift_df['Process Time']).dt.date == date]
                        # Reset the index to avoid errors when concatenating
                        same_date_day_rows.reset_index(drop=True, inplace=True)

                        # Filter the rows with the same date in night_shift_df
                        same_date_night_rows = night_shift_df[pd.to_datetime(night_shift_df['Process Time']).dt.date == date]
                        # Reset the index to avoid errors when concatenating
                        same_date_night_rows.reset_index(drop=True, inplace=True)

                        # Calculate the call volume ratio for day and night shifts
                        total_calls = len(same_date_day_rows) + len(same_date_night_rows)
                        if total_calls == 0:
                                continue

                        day_ratio = len(same_date_day_rows) / total_calls
                        night_ratio = len(same_date_night_rows) / total_calls

                        # Calculate the number of calls to select from day and night shifts
                        day_amount = int(round(day_ratio * Calls_Per_Day))
                        night_amount = Calls_Per_Day - day_amount

                        print(f"day amount: {day_amount}")
                        print(f"night amount: {night_amount}")

                        # Iterate over the rows day_amount times, or up to the length of same_date_day_rows
                        for i in range(min(day_amount, len(same_date_day_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_day_rows.loc[[i]]], ignore_index=True)

                        # Iterate over the rows night_amount times, or up to the length of same_date_night_rows
                        for i in range(min(night_amount, len(same_date_night_rows))):
                                # Add the row with the same date to present_df
                                present_df = pd.concat([present_df, same_date_night_rows.loc[[i]]], ignore_index=True)
        else:
                raise Exception("Call_Distribution_Type not found. Please select an option from the dropdown in the settings, default is a valid option")


        # CREATE OUTPUT DATAFRAME

        #generate new dataframe with columns "Event ID", "Nature", "Phone #", "Carrier", "Email"
        outputDf = pd.DataFrame(columns=["Event ID", "Nature", "Phone #", "Carrier", "Email", "Subject Line"])

        #iterate through each row in present_df
        for index, row in present_df.iterrows():
                #get the event id
                event_id = row["Event ID"]
                #get the nature
                nature = row["Nature"]
                #get the phone number
                phone_number = row["Phone #"]
                subject_line = f"Event {event_id}"
                #get the carrier by checking if the customer row has "T-MOBILE" in the string
                if "T-MOBILE" in row["Customer"]:
                        carrier = "TMOBILE"
                        email = f"{phone_number}@tmomail.net"
                elif "VERIZON" in row["Customer"]:
                        carrier = "VERIZON"
                        email = f"{phone_number}@vtext.com"
                elif "AT&T" in row["Customer"]:
                        carrier = "AT&T"
                        email = f"{phone_number}@txt.att.net, {phone_number}@mms.att.net"
                #get the email    
                #add the row to the output dataframe
                new_row = pd.DataFrame({"Event ID": [event_id], "Nature": [nature], "Phone #": [phone_number], "Carrier": [carrier], "Email": [email], "Subject Line": [subject_line]})
                outputDf = pd.concat([outputDf, new_row], ignore_index=True)
  
        # generate stats graphs
        present_df['Process Time'] = pd.to_datetime(present_df['Process Time'])
        
        # Count the number of rows for night shift and day shift
        night_shift_count = sum((present_df['Process Time'].dt.hour < 6) | (present_df['Process Time'].dt.hour >= 18))
        day_shift_count = sum((present_df['Process Time'].dt.hour >= 6) & (present_df['Process Time'].dt.hour < 18))

        # Define the labels and sizes for the pie chart
        labels = ['Night Shift', 'Day Shift']
        sizes = [night_shift_count, day_shift_count]

        # Plot the pie chart
        fig, ax = plt.subplots()
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
        ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

        plt.title('Night Shift vs Day Shift Calls Distribution')

        # Save the pie chart as an image
        buf = BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        shift_distribution_img = base64.b64encode(buf.getvalue()).decode('utf-8')
        buf.close()
        plt.close(fig)

        # Count the occurrences of each Nature Code
        nature_counts = present_df['Nature'].value_counts()

        # Plot the pie chart
        fig, ax = plt.subplots()
        ax.pie(nature_counts, labels=nature_counts.index, autopct='%1.1f%%', startangle=90)
        ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

        plt.title('Nature Codes Distribution')

        # Save the pie chart as an image
        buf = BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        nature_codes_distribution_img = base64.b64encode(buf.getvalue()).decode('utf-8')
        buf.close()
        plt.close(fig)


        # Once processing is complete, you can remove the original files (optional)
        os.remove(file1_path)
        os.remove(file2_path)
        os.remove('temp/aniali.xlsx')
        os.remove('temp/shortreport.xlsx')
        presentdf = present_df
        return render_template('processed_files.html', dataframe=outputDf, dataframeraw=presentdf, shift_distribution_img=shift_distribution_img, nature_codes_distribution_img=nature_codes_distribution_img)




if __name__ == '__main__':
        app.run(debug=True)
