## Roller
<img height="50" alt="image" src="https://github.com/user-attachments/assets/176261d6-ca0b-4745-8efe-ba67b4fccc96" />

Seamless integration between Roller and SowaanERP

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd <PATH_TO_YOUR_BENCH>
bench get-app https://github.com/mubi64/roller
bench --site <site_name> install-app roller
```

<img height="400" alt="image" src="https://github.com/user-attachments/assets/2089c3cc-4d0a-4ff7-af5f-f1324c3fb3b3" />

## 🛠️ Integration Steps

  ### 🔐 Get Access Token from Roller API

  1. Select the environment: **Playground** or **Live**.
  2. Enter your **Client ID** and **Client Secret**.
  3. Click the **Get Access Token** button.
  4. The system will fetch and save the access token from the **Roller API**.

     <img height="350" alt="image" src="https://github.com/user-attachments/assets/21294bb1-7ced-457e-bd78-22dcb8a801d9" />

 
  ### ⚙️ Set the Defaults

  5. Set the default values required for integration (e.g., default company, deafult tax template, etc.).

     <img height="350" alt="image" src="https://github.com/user-attachments/assets/a87cefe5-cc75-4c65-98db-610064412e1e" />

  ### 📥 Fetch Master / Historic Data

  6. Click **Fetch Data** to import master or historic data (e.g., products, customers, bookings) from the Roller API into SowaanERP.

     <img height="350" alt="image" src="https://github.com/user-attachments/assets/4d65c5c1-828f-40c5-af7c-7077847cd82e" />


  ### 🔗 Create Roller Webhook

  7. Create a new **Roller Webhook** and use the following request payload:

      ```json
      {
        "url": "<sowaanerp_base_url>/api/method/roller.api.booking.handle_roller_webhook",
        "enabled": "true",
        "webhooks": {
          "booking": {
            "events": [
              "Created",
              "Updated",
              "Cancelled"
            ]
          }
        },
        "authentication": {
          "apiKey": "token <api_key>:<api_secret>"
        }
      }
      ```

       - Replace `<sowaanerp_base_url>` with your actual SowaanERP instance URL.
       - Replace `<api_key>` and `<api_secret>` with the credentials of a valid user in your system.

      These credentials are required for authentication. If incorrect, Roller will not be able to create bookings in your SowaanERP instance.
      
      Ensure the user associated with the API credentials has sufficient permissions to create **Sales Invoices**, **Items**, and **Customers**.
  
      <img height="350" alt="image" src="https://github.com/user-attachments/assets/43e453b4-f4d9-4d49-b1f7-5b80d778b378" />
  
  7. Save the payload and click the **Create in Roller** button. Once created, **Roller** will automatically send booking data to **SowaanERP** whenever a booking is **created**, **updated**, or **cancelled**.

      <img height="350" alt="image" src="https://github.com/user-attachments/assets/3d8969db-5744-47ca-a9cb-b622ad3589ed" />


### 🧾 Booking & Invoice Workflow

- Bookings received from **Roller** are saved in the **Roller Booking** DocType.
- A **Sales Invoice** is automatically created or updated based on the booking status:
  - **Unpaid bookings** generate a **Draft** Sales Invoice.
  - **Fully paid bookings** update the invoice and mark it as **Paid**.
  - **Partially paid bookings** update the **Payments** section, but the invoice remains in **Draft** status.





### License

mit
