-- =====================================================
-- CREATE DATABASE
-- =====================================================

CREATE DATABASE SmartInventory;
GO

USE SmartInventory;
GO

-- =====================================================
-- 1. GEOGRAPHIC TABLES
-- =====================================================

CREATE TABLE Countries (
    CountryID   INT            PRIMARY KEY,
    CountryName NVARCHAR(100)  NOT NULL,
    Continent   NVARCHAR(100),
    Region      NVARCHAR(100)
);

CREATE TABLE StateProvinces (
    StateProvinceID   INT           PRIMARY KEY,
    StateProvinceName NVARCHAR(100) NOT NULL,
    CountryID         INT           NOT NULL,

    CONSTRAINT FK_StateProvinces_Countries
        FOREIGN KEY (CountryID) REFERENCES Countries(CountryID)
);

CREATE TABLE Cities (
    CityID          INT           PRIMARY KEY,
    CityName        NVARCHAR(100) NOT NULL,
    StateProvinceID INT           NOT NULL,
    Population      BIGINT,

    CONSTRAINT FK_Cities_StateProvinces
        FOREIGN KEY (StateProvinceID) REFERENCES StateProvinces(StateProvinceID)
);

-- =====================================================
-- 2. EMPLOYEES
-- =====================================================

CREATE TABLE Employees (
    EmployeeID    INT           PRIMARY KEY,
    FullName      NVARCHAR(100) NOT NULL,
    IsSalesperson BIT           NOT NULL DEFAULT 0
);

-- =====================================================
-- 3. LOOKUP TABLES
-- =====================================================

CREATE TABLE CustomerCategories (
    CustomerCategoryID   INT           PRIMARY KEY,
    CustomerCategoryName NVARCHAR(100) NOT NULL
);

CREATE TABLE BuyingGroups (
    BuyingGroupID   INT           PRIMARY KEY,
    BuyingGroupName NVARCHAR(100) NOT NULL
);

CREATE TABLE SupplierCategories (
    SupplierCategoryID   INT           PRIMARY KEY,
    SupplierCategoryName NVARCHAR(100) NOT NULL
);

CREATE TABLE Categories (
    CategoryID   INT           PRIMARY KEY,
    CategoryName NVARCHAR(100) NOT NULL
);

CREATE TABLE Colors (
    ColorID   INT           PRIMARY KEY,
    ColorName NVARCHAR(100) NOT NULL
);

CREATE TABLE PaymentMethods (
    PaymentMethodID   INT           PRIMARY KEY,
    PaymentMethodName NVARCHAR(100) NOT NULL
);

CREATE TABLE DeliveryMethods (
    DeliveryMethodID   INT           PRIMARY KEY,
    DeliveryMethodName NVARCHAR(100) NOT NULL
);

CREATE TABLE TransactionTypes (
    TransactionTypeID   INT           PRIMARY KEY,
    TransactionTypeName NVARCHAR(100) NOT NULL
);

-- =====================================================
-- 4. CUSTOMERS
-- =====================================================

CREATE TABLE Customers (
    CustomerID         INT           PRIMARY KEY,
    CustomerName       NVARCHAR(100) NOT NULL,
    CustomerCategoryID INT           NOT NULL,
    BuyingGroupID      INT           NULL,
    CityID             INT           NOT NULL,
    DeliveryMethodID   INT           NULL,
    PhoneNumber        NVARCHAR(30),
    WebsiteURL         NVARCHAR(200),
    CreditLimit        DECIMAL(18,2),
    AccountOpenedDate  DATE,

    CONSTRAINT FK_Customers_CustomerCategories
        FOREIGN KEY (CustomerCategoryID) REFERENCES CustomerCategories(CustomerCategoryID),

    CONSTRAINT FK_Customers_BuyingGroups
        FOREIGN KEY (BuyingGroupID) REFERENCES BuyingGroups(BuyingGroupID),

    CONSTRAINT FK_Customers_Cities
        FOREIGN KEY (CityID) REFERENCES Cities(CityID),

    CONSTRAINT FK_Customers_DeliveryMethods
        FOREIGN KEY (DeliveryMethodID) REFERENCES DeliveryMethods(DeliveryMethodID)
);

-- =====================================================
-- 5. SUPPLIERS
-- =====================================================

CREATE TABLE Suppliers (
    SupplierID         INT           PRIMARY KEY,
    SupplierName       NVARCHAR(100) NOT NULL,
    SupplierCategoryID INT           NOT NULL,
    CityID             INT           NOT NULL,
    DeliveryMethodID   INT           NULL,
    PhoneNumber        NVARCHAR(30),
    WebsiteURL         NVARCHAR(200),

    CONSTRAINT FK_Suppliers_SupplierCategories
        FOREIGN KEY (SupplierCategoryID) REFERENCES SupplierCategories(SupplierCategoryID),

    CONSTRAINT FK_Suppliers_Cities
        FOREIGN KEY (CityID) REFERENCES Cities(CityID),

    CONSTRAINT FK_Suppliers_DeliveryMethods
        FOREIGN KEY (DeliveryMethodID) REFERENCES DeliveryMethods(DeliveryMethodID)
);

-- =====================================================
-- 6. PRODUCTS
-- =====================================================

CREATE TABLE Products (
    ProductID       INT           PRIMARY KEY,
    ProductName     NVARCHAR(150) NOT NULL,
    SupplierID      INT           NOT NULL,
    CategoryID      INT           NOT NULL,
    ColorID         INT           NULL,
    Brand           NVARCHAR(100),
    UnitPrice       DECIMAL(18,2),
    TaxRate         DECIMAL(5,2),
    UnitsPerPackage INT,
    RetailPrice     DECIMAL(18,2),

    CONSTRAINT FK_Products_Suppliers
        FOREIGN KEY (SupplierID) REFERENCES Suppliers(SupplierID),

    CONSTRAINT FK_Products_Categories
        FOREIGN KEY (CategoryID) REFERENCES Categories(CategoryID),

    CONSTRAINT FK_Products_Colors
        FOREIGN KEY (ColorID) REFERENCES Colors(ColorID)
);

-- =====================================================
-- 7. INVENTORY
-- =====================================================

CREATE TABLE Inventory (
    ProductID        INT           PRIMARY KEY,
    CurrentStock     INT           NOT NULL DEFAULT 0,
    ReorderLevel     INT,
    TargetStockLevel INT,
    LastCostPrice    DECIMAL(18,2),

    CONSTRAINT FK_Inventory_Products
        FOREIGN KEY (ProductID) REFERENCES Products(ProductID),

    CONSTRAINT CHK_Inventory_Stock
        CHECK (CurrentStock >= 0)
);

-- =====================================================
-- 8. ORDERS
-- =====================================================

CREATE TABLE Orders (
    OrderID              INT  PRIMARY KEY,
    CustomerID           INT  NOT NULL,
    EmployeeID           INT  NOT NULL,
    OrderDate            DATE NOT NULL,
    ExpectedDeliveryDate DATE,

    CONSTRAINT FK_Orders_Customers
        FOREIGN KEY (CustomerID) REFERENCES Customers(CustomerID),

    CONSTRAINT FK_Orders_Employees
        FOREIGN KEY (EmployeeID) REFERENCES Employees(EmployeeID)
);

-- =====================================================
-- 9. ORDER DETAILS
-- =====================================================

CREATE TABLE OrderDetails (
    OrderDetailID INT           PRIMARY KEY,
    OrderID       INT           NOT NULL,
    ProductID     INT           NOT NULL,
    Quantity      INT           NOT NULL,
    UnitPrice     DECIMAL(18,2),
    TaxRate       DECIMAL(5,2),
    LineTotal     DECIMAL(18,2),
    ProfitAmount  DECIMAL(18,2),

    CONSTRAINT FK_OrderDetails_Orders
        FOREIGN KEY (OrderID) REFERENCES Orders(OrderID),

    CONSTRAINT FK_OrderDetails_Products
        FOREIGN KEY (ProductID) REFERENCES Products(ProductID),

    CONSTRAINT CHK_OrderDetails_Quantity
        CHECK (Quantity > 0)
);

-- =====================================================
-- 10. INVOICES
-- =====================================================

CREATE TABLE Invoices (
    InvoiceID        INT  PRIMARY KEY,
    OrderID          INT  NOT NULL,
    CustomerID       INT  NOT NULL,
    EmployeeID       INT  NOT NULL,
    DeliveryMethodID INT  NULL,
    InvoiceDate      DATE NOT NULL,

    CONSTRAINT FK_Invoices_Orders
        FOREIGN KEY (OrderID) REFERENCES Orders(OrderID),

    CONSTRAINT FK_Invoices_Customers
        FOREIGN KEY (CustomerID) REFERENCES Customers(CustomerID),

    CONSTRAINT FK_Invoices_Employees
        FOREIGN KEY (EmployeeID) REFERENCES Employees(EmployeeID),

    CONSTRAINT FK_Invoices_DeliveryMethods
        FOREIGN KEY (DeliveryMethodID) REFERENCES DeliveryMethods(DeliveryMethodID)
);

-- =====================================================
-- 11. INVOICE DETAILS
-- =====================================================

CREATE TABLE InvoiceDetails (
    InvoiceDetailID INT           PRIMARY KEY,
    InvoiceID       INT           NOT NULL,
    ProductID       INT           NOT NULL,
    Quantity        INT           NOT NULL,
    UnitPrice       DECIMAL(18,2),
    TaxRate         DECIMAL(5,2),
    LineTotal       DECIMAL(18,2),
    ProfitAmount    DECIMAL(18,2),

    CONSTRAINT FK_InvoiceDetails_Invoices
        FOREIGN KEY (InvoiceID) REFERENCES Invoices(InvoiceID),

    CONSTRAINT FK_InvoiceDetails_Products
        FOREIGN KEY (ProductID) REFERENCES Products(ProductID),

    CONSTRAINT CHK_InvoiceDetails_Quantity
        CHECK (Quantity > 0)
);

-- =====================================================
-- 12. PURCHASE ORDERS
-- =====================================================

CREATE TABLE PurchaseOrders (
    PurchaseOrderID      INT  PRIMARY KEY,
    SupplierID           INT  NOT NULL,
    DeliveryMethodID     INT  NULL,
    PurchaseOrderDate    DATE NOT NULL,
    ExpectedDeliveryDate DATE,

    CONSTRAINT FK_PurchaseOrders_Suppliers
        FOREIGN KEY (SupplierID) REFERENCES Suppliers(SupplierID),


    CONSTRAINT FK_PurchaseOrders_DeliveryMethods
        FOREIGN KEY (DeliveryMethodID) REFERENCES DeliveryMethods(DeliveryMethodID)
);

-- =====================================================
-- 13. PURCHASE ORDER DETAILS
-- =====================================================

CREATE TABLE PurchaseOrderDetails (
    PurchaseOrderDetailID INT           PRIMARY KEY,
    PurchaseOrderID       INT           NOT NULL,
    ProductID             INT           NOT NULL,
    QuantityOrdered       INT           NOT NULL,
    UnitCostPrice         DECIMAL(18,2),

    CONSTRAINT FK_PurchaseOrderDetails_PurchaseOrders
        FOREIGN KEY (PurchaseOrderID) REFERENCES PurchaseOrders(PurchaseOrderID),

    CONSTRAINT FK_PurchaseOrderDetails_Products
        FOREIGN KEY (ProductID) REFERENCES Products(ProductID),

    CONSTRAINT CHK_PurchaseOrderDetails_Quantity
        CHECK (QuantityOrdered > 0)
);

-- =====================================================
-- 14. CUSTOMER TRANSACTIONS
-- =====================================================

CREATE TABLE CustomerTransactions (
    CustomerTransactionID INT           PRIMARY KEY,
    CustomerID            INT           NOT NULL,
    InvoiceID             INT           NULL,
    TransactionTypeID     INT           NOT NULL,
    PaymentMethodID       INT           NULL,
    TransactionDate       DATE          NOT NULL,
    NetAmount             DECIMAL(18,2),
    TaxAmount             DECIMAL(18,2),
    TransactionAmount     DECIMAL(18,2),
    RemainingBalance      DECIMAL(18,2),

    CONSTRAINT FK_CustomerTransactions_Customers
        FOREIGN KEY (CustomerID) REFERENCES Customers(CustomerID),

    CONSTRAINT FK_CustomerTransactions_Invoices
        FOREIGN KEY (InvoiceID) REFERENCES Invoices(InvoiceID),

    CONSTRAINT FK_CustomerTransactions_TransactionTypes
        FOREIGN KEY (TransactionTypeID) REFERENCES TransactionTypes(TransactionTypeID),

    CONSTRAINT FK_CustomerTransactions_PaymentMethods
        FOREIGN KEY (PaymentMethodID) REFERENCES PaymentMethods(PaymentMethodID)
);

-- =====================================================
-- 15. SUPPLIER TRANSACTIONS
-- =====================================================

CREATE TABLE SupplierTransactions (
    SupplierTransactionID INT           PRIMARY KEY,
    SupplierID            INT           NOT NULL,
    PurchaseOrderID       INT           NULL,
    TransactionTypeID     INT           NOT NULL,
    PaymentMethodID       INT           NULL,
    TransactionDate       DATE          NOT NULL,
    NetAmount             DECIMAL(18,2),
    TaxAmount             DECIMAL(18,2),
    TransactionAmount     DECIMAL(18,2),
    RemainingBalance      DECIMAL(18,2),

    CONSTRAINT FK_SupplierTransactions_Suppliers
        FOREIGN KEY (SupplierID) REFERENCES Suppliers(SupplierID),

    CONSTRAINT FK_SupplierTransactions_PurchaseOrders
        FOREIGN KEY (PurchaseOrderID) REFERENCES PurchaseOrders(PurchaseOrderID),

    CONSTRAINT FK_SupplierTransactions_TransactionTypes
        FOREIGN KEY (TransactionTypeID) REFERENCES TransactionTypes(TransactionTypeID),

    CONSTRAINT FK_SupplierTransactions_PaymentMethods
        FOREIGN KEY (PaymentMethodID) REFERENCES PaymentMethods(PaymentMethodID)
);

-- =====================================================
-- 16. INVENTORY TRANSACTIONS
-- =====================================================

CREATE TABLE InventoryTransactions (
    TransactionID     INT      PRIMARY KEY,
    ProductID         INT      NOT NULL,
    TransactionTypeID INT      NOT NULL,
    CustomerID        INT      NULL,
    SupplierID        INT      NULL,
    InvoiceID         INT      NULL,
    PurchaseOrderID   INT      NULL,
    Quantity          INT      NOT NULL,
    TransactionDate   DATETIME NOT NULL,

    CONSTRAINT FK_InventoryTransactions_Products
        FOREIGN KEY (ProductID) REFERENCES Products(ProductID),

    CONSTRAINT FK_InventoryTransactions_TransactionTypes
        FOREIGN KEY (TransactionTypeID) REFERENCES TransactionTypes(TransactionTypeID),

    CONSTRAINT FK_InventoryTransactions_Customers
        FOREIGN KEY (CustomerID) REFERENCES Customers(CustomerID),

    CONSTRAINT FK_InventoryTransactions_Suppliers
        FOREIGN KEY (SupplierID) REFERENCES Suppliers(SupplierID),
    CONSTRAINT FK_InventoryTransactions_Invoices
        FOREIGN KEY (InvoiceID) REFERENCES Invoices(InvoiceID),

    CONSTRAINT FK_InventoryTransactions_PurchaseOrders
        FOREIGN KEY (PurchaseOrderID) REFERENCES PurchaseOrders(PurchaseOrderID)
);

-- =====================================================
-- RELATIONSHIPS SUMMARY
-- =====================================================
-- Geographic     : Countries 1--M StateProvinces 1--M Cities
-- Cities         : Cities 1--M Customers
--                  Cities 1--M Suppliers
-- Delivery       : DeliveryMethods 1--M Customers
--                  DeliveryMethods 1--M Suppliers
--                  DeliveryMethods 1--M Invoices
--                  DeliveryMethods 1--M PurchaseOrders
-- Customers      : CustomerCategories 1--M Customers
--                  BuyingGroups 1--M Customers
-- Suppliers      : SupplierCategories 1--M Suppliers
-- Products       : Suppliers 1--M Products
--                  Categories 1--M Products
--                  Colors 1--M Products
-- Inventory      : Products 1--1 Inventory
-- Orders         : Customers 1--M Orders
--                  Employees 1--M Orders
--                  Orders 1--M OrderDetails
--                  Products 1--M OrderDetails
-- Invoices       : Orders 1--M Invoices
--                  Customers 1--M Invoices
--                  Employees 1--M Invoices
--                  Invoices 1--M InvoiceDetails
--                  Products 1--M InvoiceDetails
-- PurchaseOrders : Suppliers 1--M PurchaseOrders
--                  DeliveryMethods 1--M PurchaseOrders
--                  PurchaseOrders 1--M PurchaseOrderDetails
--                  Products 1--M PurchaseOrderDetails
--                  PurchaseOrders 1--M PurchaseOrderDetails
--                  Products 1--M PurchaseOrderDetails
-- Transactions   : Customers 1--M CustomerTransactions
--                  Invoices 1--M CustomerTransactions
--                  PaymentMethods 1--M CustomerTransactions
--                  TransactionTypes 1--M CustomerTransactions
--                  Suppliers 1--M SupplierTransactions
--                  PurchaseOrders 1--M SupplierTransactions
--                  PaymentMethods 1--M SupplierTransactions
--                  TransactionTypes 1--M SupplierTransactions
--                  Products 1--M InventoryTransactions
--                  TransactionTypes 1--M InventoryTransactions
--                  Customers 1--M InventoryTransactions
--                  Suppliers 1--M InventoryTransactions
-- =====================================================

SELECT
    name        AS TableName,
    create_date AS CreatedAt
FROM sys.tables
ORDER BY create_date;